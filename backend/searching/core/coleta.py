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
from ..db.models import Coleta, Configuracao, Execucao, Produto
from ..db.session import BACKEND_DIR, CONFIG_PADRAO
from .lojas import modelo_simples, normalizar, normalizar_loja
from .navegador import Navegador
from .precos import parse_preco_centavos
from .status import StatusColeta
from .trava import TravaColeta
from .validacao import Leitura, classificar, eh_suspeito

log = logging.getLogger("searching.coleta")

PRINTS_DIR = BACKEND_DIR / "prints"
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
        navegador = navegador_factory(headless=cfg["navegador_headless"] == "1")
        retentativas = int(cfg["retentativas"])
        base_espera = float(cfg["espera_retentativa_s"])
        contagem: dict[str, int] = {}

        try:
            limite_bloqueios = int(cfg["bloqueios_para_interromper"])
            bloqueios_seguidos: dict[str, int] = {}
            ja_pediu: list[bool] = []

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
                            dormir(random.uniform(float(cfg["pausa_min_s"]), float(cfg["pausa_max_s"])))
                        ja_pediu.append(True)
                        for tentativa in range(retentativas + 1):
                            resultado = _coletar_uma_vez(navegador, adaptador, produto, cfg, pasta)
                            if resultado.status not in STATUS_RETENTAVEIS or tentativa == retentativas:
                                break
                            espera = base_espera * (3**tentativa)
                            log.info("[exec %s] %s: %s, nova tentativa em %.0fs", exec_id, produto.nome_comercial, resultado.status.value, espera)
                            dormir(espera)

                    status, detalhe = resultado.status, resultado.detalhe
                    if status == StatusColeta.OK and eh_suspeito(
                        resultado.pix_centavos, _ultimo_pix_valido(s, produto.id), float(cfg["variacao_suspeita_pct"])
                    ):
                        status, detalhe = StatusColeta.SUSPEITO, "variação acima do limite em relação à última coleta válida"

                    leitura = resultado.leitura
                    s.add(
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
                    s.commit()
                    contagem[status.value] = contagem.get(status.value, 0) + 1
                    log.info("[exec %s] %s -> %s %s", exec_id, produto.nome_comercial, status.value, detalhe)
                    if fez_requisicao and adaptador is not None:
                        if status == StatusColeta.BLOQUEIO:
                            bloqueios_seguidos[loja] = bloqueios_seguidos.get(loja, 0) + 1
                        else:
                            bloqueios_seguidos[loja] = 0
                return fez_requisicao

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
                s.commit()
                resumo = {
                    "execucao_id": exec_id,
                    "total": execucao.total,
                    "ok": execucao.ok,
                    "falhas": execucao.falhas,
                    "por_status": contagem,
                    "pasta": execucao.iniciada_em.strftime("%Y-%m-%d"),
                }
            log.info("[exec %s] finalizada: %s", exec_id, resumo)
        return resumo
