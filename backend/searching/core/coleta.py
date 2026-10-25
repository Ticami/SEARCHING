"""Orquestra uma execução de coleta: produto a produto, com retentativas, print e registro no banco."""
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from selenium.common.exceptions import InvalidSessionIdException, TimeoutException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..adapters import adaptador_para
from ..alerts import servico as alertas
from ..alerts.servico import Notificador
from ..db import links as repo_links
from ..db.models import Coleta, Configuracao, Execucao, Produto, RevisaoLink, TentativaRecuperacao
from ..db.session import BACKEND_DIR, CONFIG_PADRAO, PRINTS_DIR
from ..links.recuperacao import recuperar
from .lojas import modelo_simples, normalizar, normalizar_loja
from .navegador import Navegador
from .precos import parse_preco_centavos
from .status import STATUS_RECUPERAVEIS, StatusColeta
from .trava import TravaColeta
from .validacao import Leitura, classificar, eh_suspeito

log = logging.getLogger("searching.coleta")

# Falhas que podem ser passageiras (rede lenta, página carregando): vale tentar de novo.
STATUS_RETENTAVEIS = {StatusColeta.TIMEOUT, StatusColeta.ERRO_INESPERADO, StatusColeta.PRECO_NAO_ENCONTRADO}


@dataclass
class Resultado:
    status: StatusColeta
    detalhe: str = ""
    leitura: Leitura | None = None
    caminho_print: str | None = None
    pix_centavos: int | None = None
    cartao_centavos: int | None = None


def _config(s: Session) -> dict[str, str]:
    valores = dict(CONFIG_PADRAO)
    valores.update({c.chave: c.valor for c in s.scalars(select(Configuracao))})
    return valores


def _nome_arquivo(nome: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", nome).strip()


def _tirar_print(driver, pasta: Path, nome: str, quando: datetime) -> str | None:
    """Screenshot do próprio navegador (não depende de janela em foco nem da tela do Windows)."""
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{_nome_arquivo(modelo_simples(nome))}_{quando:%H-%M-%S}.png"
        if driver.save_screenshot(str(destino)):
            return destino.relative_to(BACKEND_DIR).as_posix() if destino.is_relative_to(BACKEND_DIR) else str(destino)
    except Exception as exc:
        log.warning("Falha ao salvar print de %s: %s", nome, exc)
    return None


def _coletar_uma_vez(navegador: Navegador, adaptador, produto: Produto, cfg: dict, pasta_prints: Path) -> Resultado:
    timeout = float(cfg["timeout_produto_s"])
    try:
        try:
            driver = navegador.obter()
            leitura = adaptador.carregar(driver, produto.url_atual, timeout)
        except InvalidSessionIdException:
            driver = navegador.reiniciar()
            leitura = adaptador.carregar(driver, produto.url_atual, timeout)

        # O print vem antes de qualquer clique: é a evidência da página como o cliente vê.
        caminho = _tirar_print(driver, pasta_prints, produto.nome_comercial, datetime.now())

        pix = parse_preco_centavos(leitura.pix_texto)
        status, detalhe = classificar(
            leitura, pix, produto.marca, produto.modelo, produto.armazenamento, produto.extras
        )
        cartao = None
        if status == StatusColeta.OK:
            leitura.cartao_texto = adaptador.ler_cartao_1x(driver, timeout)
            cartao = parse_preco_centavos(leitura.cartao_texto)
        return Resultado(status, detalhe, leitura, caminho, pix, cartao)
    except TimeoutException as exc:
        return Resultado(StatusColeta.TIMEOUT, f"timeout: {exc.msg or exc}")
    except Exception as exc:
        return Resultado(StatusColeta.ERRO_INESPERADO, f"{type(exc).__name__}: {exc}")


def _ultimo_pix_valido(s: Session, produto_id: int) -> int | None:
    return s.scalar(
        select(Coleta.preco_pix_centavos)
        .where(
            Coleta.produto_id == produto_id,
            Coleta.status == StatusColeta.OK.value,
            Coleta.preco_pix_centavos.is_not(None),
        )
        .order_by(Coleta.coletado_em.desc())
        .limit(1)
    )


def _status_final(s: Session, produto: Produto, resultado: Resultado, cfg: dict) -> tuple[StatusColeta, str]:
    """Aplica a validação de sanidade (RF-09): variação grande demais vira SUSPEITO."""
    if resultado.status == StatusColeta.OK and eh_suspeito(
        resultado.pix_centavos, _ultimo_pix_valido(s, produto.id), float(cfg["variacao_suspeita_pct"])
    ):
        return StatusColeta.SUSPEITO, "variação acima do limite em relação à última coleta válida"
    return resultado.status, resultado.detalhe


def _salvar_coleta(s: Session, exec_id: int, produto: Produto, resultado: Resultado, status: StatusColeta, detalhe: str) -> Coleta:
    leitura = resultado.leitura
    coleta = (
        Coleta(
            execucao_id=exec_id,
            produto_id=produto.id,
            coletado_em=datetime.now(),
            status=status.value,
            titulo_lido=leitura.titulo if leitura else None,
            vendedor=leitura.vendedor if leitura else None,
            preco_pix_centavos=resultado.pix_centavos,
            preco_cartao_1x_centavos=resultado.cartao_centavos,
            texto_bruto={
                "pix": leitura.pix_texto if leitura else None,
                "cartao_1x": leitura.cartao_texto if leitura else None,
                "url_final": leitura.url_final if leitura else None,
            },
            caminho_print=resultado.caminho_print,
            erro_detalhe=detalhe or None,
        )
    )
    s.add(coleta)
    s.commit()
    return coleta


def _pode_recuperar(s: Session, produto: Produto, cfg: dict) -> bool:
    """Respeita o limite diário de tentativas (RF-21) e não repete enquanto há revisão pendente."""
    if cfg["recuperacao_automatica"] != "1":
        return False
    if s.scalar(select(RevisaoLink.id).where(RevisaoLink.produto_id == produto.id, RevisaoLink.estado == "pendente")):
        return False
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    feitas = len(
        s.scalars(
            select(TentativaRecuperacao.id).where(TentativaRecuperacao.produto_id == produto.id, TentativaRecuperacao.em >= hoje)
        ).all()
    )
    return feitas < int(cfg["buscas_por_produto_dia"])


def _recuperar_link(s, navegador, adaptador, produto, resultado, exec_id, cfg, pausar) -> str:
    """Tenta achar o link novo. Devolve 'corrigido', 'revisao' ou 'bloqueada'."""
    rec = recuperar(
        navegador, adaptador, produto, resultado.leitura,
        float(cfg["confianca_minima_autocorrecao"]), float(cfg["timeout_produto_s"]), pausar,
    )
    if rec.bloqueada:
        return "bloqueada"  # sem registrar tentativa: a loja barrou, não houve busca de verdade
    if rec.escolhido:
        c = rec.escolhido
        repo_links.trocar_url(
            s, produto, c.url, f"recuperação automática ({resultado.status.value}, {c.estrategia})", "automatico", c.nota
        )
        s.add(TentativaRecuperacao(produto_id=produto.id, execucao_id=exec_id, estrategia=c.estrategia, resultado="corrigido"))
        s.commit()
        return "corrigido"
    s.add(
        RevisaoLink(
            produto_id=produto.id,
            execucao_id=exec_id,
            motivo=resultado.status.value,
            candidatos=[c.como_dict() for c in rec.candidatos],
        )
    )
    s.add(
        TentativaRecuperacao(
            produto_id=produto.id, execucao_id=exec_id, estrategia=rec.estrategia,
            resultado="revisao" if rec.candidatos else "sem_candidato",
        )
    )
    s.commit()
    return "revisao"


def _selecionar(s: Session, stores, include, exclude) -> list[Produto]:
    lojas = {normalizar_loja(x) for x in (stores or [])}
    inc = {normalizar(modelo_simples(x)) for x in (include or []) if str(x).strip()}
    exc = {normalizar(modelo_simples(x)) for x in (exclude or []) if str(x).strip()}
    escolhidos = []
    for p in s.scalars(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.id)):
        chave = normalizar(modelo_simples(p.nome_comercial))
        if lojas and normalizar_loja(p.loja) not in lojas:
            continue
        if inc and chave not in inc:
            continue
        if exc and chave in exc:
            continue
        escolhidos.append(p)
    return escolhidos


def executar_coleta(
    fabrica: sessionmaker[Session],
    origem: str = "manual",
    stores=None,
    include=None,
    exclude=None,
    navegador_factory=Navegador,
    adaptador_de=adaptador_para,
    dormir=time.sleep,
    prints_dir: Path = PRINTS_DIR,
    trava: TravaColeta | None = None,
    notificador: Notificador | None = None,
) -> dict:
    """Roda uma coleta completa e devolve o resumo. Lança ColetaEmAndamento se já houver outra."""
    with (trava or TravaColeta()):
        with fabrica() as s:
            cfg = _config(s)
            produtos = _selecionar(s, stores, include, exclude)
            execucao = Execucao(iniciada_em=datetime.now(), origem=origem, total=len(produtos))
            s.add(execucao)
            s.commit()
            exec_id = execucao.id
            ids = [p.id for p in produtos]

        log.info("[exec %s] iniciada (%s): %d produtos", exec_id, origem, len(ids))
        notificador = notificador or Notificador()
        navegador = navegador_factory(headless=cfg["navegador_headless"] == "1")
        retentativas = int(cfg["retentativas"])
        base_espera = float(cfg["espera_retentativa_s"])
        contagem: dict[str, int] = {}

        try:
            limite_bloqueios = int(cfg["bloqueios_para_interromper"])
            bloqueios_seguidos: dict[str, int] = {}
            ja_pediu: list[bool] = []
            extras = {"corrigidos": 0, "revisao": 0, "alertas": 0}

            def pausar() -> None:
                dormir(random.uniform(float(cfg["pausa_min_s"]), float(cfg["pausa_max_s"])))

            def processar(produto_id: int) -> bool:
                """Coleta um produto. Devolve True se fez requisições à loja."""
                fez_requisicao = True
                with fabrica() as s:
                    produto = s.get(Produto, produto_id)
                    adaptador = adaptador_de(produto.url_atual)
                    loja = normalizar_loja(produto.loja)
                    inicio = datetime.now()
                    pasta = prints_dir / inicio.strftime("%Y-%m-%d")

                    if adaptador is None:
                        resultado = Resultado(StatusColeta.ERRO_INESPERADO, f"sem adaptador para a loja de {produto.url_atual}")
                    elif limite_bloqueios and bloqueios_seguidos.get(loja, 0) >= limite_bloqueios:
                        # A loja já recusou nos produtos anteriores: não insiste.
                        fez_requisicao = False
                        resultado = Resultado(
                            StatusColeta.BLOQUEIO,
                            f"loja interrompida após {limite_bloqueios} bloqueios seguidos; sem nova requisição",
                        )
                    else:
                        # Pausa antes de pedir a página (nunca antes de produtos pulados nem do primeiro).
                        if ja_pediu:
                            pausar()
                        ja_pediu.append(True)
                        for tentativa in range(retentativas + 1):
                            resultado = _coletar_uma_vez(navegador, adaptador, produto, cfg, pasta)
                            if resultado.status not in STATUS_RETENTAVEIS or tentativa == retentativas:
                                break
                            espera = base_espera * (3**tentativa)
                            log.info("[exec %s] %s: %s, nova tentativa em %.0fs", exec_id, produto.nome_comercial, resultado.status.value, espera)
                            dormir(espera)

                    status, detalhe = _status_final(s, produto, resultado, cfg)
                    coleta_final = _salvar_coleta(s, exec_id, produto, resultado, status, detalhe)
                    log.info("[exec %s] %s -> %s %s", exec_id, produto.nome_comercial, status.value, detalhe)

                    if fez_requisicao and adaptador is not None and resultado.status in STATUS_RECUPERAVEIS and _pode_recuperar(s, produto, cfg):
                        desfecho = _recuperar_link(s, navegador, adaptador, produto, resultado, exec_id, cfg, pausar)
                        log.info("[exec %s] %s: recuperação de link -> %s", exec_id, produto.nome_comercial, desfecho)
                        if desfecho == "corrigido":
                            pausar()
                            resultado = _coletar_uma_vez(navegador, adaptador, produto, cfg, pasta)  # refaz a coleta
                            status, detalhe = _status_final(s, produto, resultado, cfg)
                            coleta_final = _salvar_coleta(s, exec_id, produto, resultado, status, detalhe)
                            extras["corrigidos"] += 1
                            log.info("[exec %s] %s (link novo) -> %s %s", exec_id, produto.nome_comercial, status.value, detalhe)
                        elif desfecho == "revisao":
                            extras["revisao"] += 1
                        elif desfecho == "bloqueada":
                            status = StatusColeta.BLOQUEIO
                            detalhe = "loja bloqueou durante a recuperação do link"

                    contagem[status.value] = contagem.get(status.value, 0) + 1
                    if status == StatusColeta.OK and alertas.processar_coleta(s, produto, coleta_final, cfg, notificador):
                        extras["alertas"] += 1
                    if fez_requisicao and adaptador is not None:
                        if status == StatusColeta.BLOQUEIO:
                            bloqueios_seguidos[loja] = bloqueios_seguidos.get(loja, 0) + 1
                        else:
                            bloqueios_seguidos[loja] = 0
                return fez_requisicao

            with fabrica() as s:  # alertas que falharam antes são reenviados primeiro (e não duplicam os novos)
                reenviados = alertas.reenviar_pendentes(s, notificador)
                if reenviados:
                    log.info("[exec %s] %d alerta(s) pendente(s) reenviado(s)", exec_id, reenviados)

            for produto_id in ids:
                try:
                    processar(produto_id)
                except Exception:
                    # Uma falha num produto nunca interrompe os demais.
                    log.exception("[exec %s] erro ao processar produto id=%s", exec_id, produto_id)
                    chave = StatusColeta.ERRO_INESPERADO.value
                    contagem[chave] = contagem.get(chave, 0) + 1
        finally:
            navegador.fechar()
            with fabrica() as s:
                execucao = s.get(Execucao, exec_id)
                execucao.finalizada_em = datetime.now()
                execucao.ok = contagem.get(StatusColeta.OK.value, 0)
                execucao.falhas = sum(contagem.values()) - execucao.ok
                execucao.links_corrigidos = extras["corrigidos"]
                execucao.em_revisao = extras["revisao"]
                s.commit()
                resumo = {
                    "execucao_id": exec_id,
                    "total": execucao.total,
                    "ok": execucao.ok,
                    "falhas": execucao.falhas,
                    "links_corrigidos": execucao.links_corrigidos,
                    "em_revisao": execucao.em_revisao,
                    "alertas": extras["alertas"],
                    "por_status": contagem,
                    "pasta": execucao.iniciada_em.strftime("%Y-%m-%d"),
                }
            log.info("[exec %s] finalizada: %s", exec_id, resumo)
        if cfg["resumo_diario_email"] == "1" and resumo["total"] > 0:
            with fabrica() as s_resumo:
                enviado, mensagem = alertas.enviar_resumo(resumo, notificador, s=s_resumo)
            log.info("[exec %s] resumo por e-mail: %s", exec_id, mensagem if not enviado else "enviado")
        return resumo
