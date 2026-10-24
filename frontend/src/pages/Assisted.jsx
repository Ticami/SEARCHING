import React, { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../auth.jsx";

const INTERVALO_MS = 3000; // a extensão também impõe este intervalo mínimo entre páginas

const ETAPAS = {
  autorizando: "Pedindo autorização ao servidor…",
  navegando: "Abrindo a página no Chrome…",
  lendo: "Lendo a página…",
  menu: "Abrindo as opções de pagamento…",
  enviando: "Enviando ao SEARCHING…",
};

const STATUS_COR = { OK: "#34d399", SUSPEITO: "#fbbf24", BLOQUEIO: "#f87171", LINK_QUEBRADO: "#f87171" };

const EXPLICACAO = {
  BLOQUEIO: "A loja bloqueou esta página. Nada foi forçado: ficou registrado como BLOQUEIO, com o print do erro.",
  LINK_QUEBRADO: "O link não leva a uma página de produto. Marque como link quebrado para ele entrar na fila de Revisão.",
  PRODUTO_DIVERGENTE: "A página não bate com o cadastro (marca, modelo, armazenamento ou variante). Confira o link.",
  PRECO_NAO_ENCONTRADO: "Não achei o preço na página. Use Refazer; se repetir, o layout da loja pode ter mudado.",
  INDISPONIVEL: "O produto está sem estoque.",
  SUSPEITO: "O preço variou demais em relação à última coleta válida. Confira o print antes de confiar.",
};

async function api(url, corpo) {
  const res = await fetch(url, {
    method: corpo === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `Erro ${res.status}`);
  return json;
}

export default function Assisted() {
  const { modo } = useAuth();
  const [ext, setExt] = useState({ estado: "procurando" });
  const [sess, setSess] = useState(null);
  const [atualId, setAtualId] = useState(null);
  const [etapa, setEtapa] = useState(null);
  const [avisos, setAvisos] = useState([]);
  const [mostrarErros, setMostrarErros] = useState(false);
  const [aguardando, setAguardando] = useState(false);
  const [livreEm, setLivreEm] = useState(0);
  const [agora, setAgora] = useState(Date.now());
  const [msg, setMsg] = useState("");
  const [foraDaFila, setForaDaFila] = useState([]);
  const [resumo, setResumo] = useState(null);
  const [recorte, setRecorte] = useState(() => Number(localStorage.getItem("assistida_recorte") || 0));
  const seqRef = useRef(0);
  const idRef = useRef(0);
  const pendentes = useRef({});

  // ---------- conversa com a extensão (ponte.js) ----------
  const enviarExt = useCallback((tipo, dados = {}) => {
    return new Promise((resolve, reject) => {
      const id = ++idRef.current;
      const t = setTimeout(() => {
        delete pendentes.current[id];
        reject(new Error("A extensão não respondeu."));
      }, 4000);
      pendentes.current[id] = (r) => {
        clearTimeout(t);
        resolve(r);
      };
      window.postMessage({ origem: "searching-app", id, tipo, ...dados }, window.location.origin);
    });
  }, []);

  const carregarSessao = useCallback(async () => {
    try {
      const s = await api("/api/assistida/sessao");
      setSess(s);
      return s;
    } catch (e) {
      setMsg(e.message);
      return null;
    }
  }, []);

  useEffect(() => {
    const onMsg = (e) => {
      if (e.source !== window || e.origin !== window.location.origin) return;
      const d = e.data;
      if (!d || d.origem !== "searching-ext") return;
      if (d.tipo === "resposta" && pendentes.current[d.id]) {
        pendentes.current[d.id](d);
        delete pendentes.current[d.id];
      } else if (d.tipo === "evento" && d.seq === seqRef.current) {
        setEtapa(d);
        if (d.etapa === "aviso" && d.detalhe) setAvisos((a) => (a.includes(d.detalhe) ? a : [...a, d.detalhe]));
        if (d.etapa === "pronto") {
          setAguardando(false);
          carregarSessao();
        } else if (d.etapa === "erro") {
          setAguardando(false);
          setMsg(d.detalhe || "Falha na captura.");
          if (/pareie de novo/i.test(d.detalhe || "")) setExt({ estado: "ausente" }); // token revogado: mostra "Procurar de novo" (re-pareia)
        }
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [carregarSessao]);

  // detecta a extensão e faz o pareamento (entrega o token e a preferência de recorte)
  const parear = useCallback(async () => {
    setExt({ estado: "procurando" });
    for (let i = 0; i < 6; i++) {
      try {
        const r = await enviarExt("ping");
        if (r && r.ok) {
          if (modo === "hospedado") {
            // token por usuário: só cria um novo se a extensão ainda não estiver pareada (ou se o antigo foi revogado)
            const entrega = !r.pareado ? await api("/api/extensao/parear", {}).then(({ token }) => enviarExt("configurar", { token, recorteTopoPx: recorte })) : await enviarExt("configurar", { recorteTopoPx: recorte });
            if (!entrega.ok) {
              setExt({ estado: "outro_servidor", detalhe: entrega.erro, servidor: r.servidor });
              return;
            }
          } else {
            const { token, servidor } = await api("/api/assistida/token");
            await enviarExt("configurar", { token, servidor, recorteTopoPx: recorte });
          }
          setExt({ estado: "ok", versao: r.versao });
          return;
        }
      } catch {
        /* tenta de novo */
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    setExt({ estado: "ausente" });
  }, [enviarExt, recorte, modo]);

  useEffect(() => {
    parear();
    carregarSessao();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (livreEm <= Date.now()) return undefined;
    const t = setInterval(() => setAgora(Date.now()), 250);
    return () => clearInterval(t);
  }, [livreEm]);

  // ---------- ações ----------
  const itens = sess?.ativa ? sess.itens : [];
  const atual = itens.find((i) => i.produto_id === atualId) || null;
  const resultado = atual?.coleta || null;
  const restamMs = Math.max(0, livreEm - agora);
  const proximoPendente = itens.find((i) => !i.concluido && i.produto_id !== atualId) || itens.find((i) => !i.concluido) || null;
  const podeNavegar = ext.estado === "ok" && !aguardando && restamMs === 0;
  const podeProximo = podeNavegar && sess?.ativa && (atual === null || atual.concluido);

  const abrir = useCallback(
    async (item, execucaoId = sess?.execucao_id) => {
      if (!item || execucaoId == null) return;
      setMsg("");
      setEtapa(null);
      setAvisos([]);
      const seq = ++seqRef.current;
      setAtualId(item.produto_id);
      setAguardando(true);
      try {
        const r = await enviarExt("navegar", { url: item.url, produtoId: item.produto_id, execucaoId, seq });
        if (!r.ok) {
          setAguardando(false);
          setMsg(r.erro === "aguarde" ? `Calma: aguarde ${Math.ceil((r.aguardarMs || 0) / 1000)} s para a próxima página.` : r.erro || "A extensão recusou o pedido.");
          if (r.erro === "aguarde") setLivreEm(Date.now() + (r.aguardarMs || INTERVALO_MS));
          return;
        }
        setLivreEm(Date.now() + INTERVALO_MS);
        setAgora(Date.now());
      } catch (e) {
        setAguardando(false);
        setMsg(e.message);
      }
    },
    [enviarExt, sess]
  );

  const iniciar = async () => {
    setMsg("");
    setResumo(null);
    try {
      const s = await api("/api/assistida/iniciar", { stores: ["magalu"] });
      setSess(s);
      setForaDaFila((s.em_coleta_por_outros || []).map((x) => `${x.produto} (${x.por})`));
      setAtualId(null);
      const primeiro = s.itens.find((i) => !i.concluido);
      if (primeiro) await abrir(primeiro, s.execucao_id);
    } catch (e) {
      setMsg(e.message);
    }
  };

  const proximo = useCallback(() => {
    if (!podeProximo) return;
    if (!proximoPendente) {
      setMsg("Todos os produtos foram coletados. Clique em Encerrar para fechar a execução.");
      return;
    }
    abrir(proximoPendente);
  }, [podeProximo, proximoPendente, abrir]);

  const pular = async () => {
    if (!atual) return;
    try {
      await api("/api/assistida/pular", { execucao_id: sess.execucao_id, produto_id: atual.produto_id });
      const s = await carregarSessao();
      const prox = s?.itens.find((i) => !i.concluido);
      setAtualId(null);
      if (prox && ext.estado === "ok") setTimeout(() => abrir(prox, s.execucao_id), Math.max(0, livreEm - Date.now()));
    } catch (e) {
      setMsg(e.message);
    }
  };
  const linkQuebrado = async () => {
    if (!atual) return;
    try {
      await api("/api/assistida/link-quebrado", { execucao_id: sess.execucao_id, produto_id: atual.produto_id });
      await carregarSessao();
      setAguardando(false);
    } catch (e) {
      setMsg(e.message);
    }
  };

  const encerrar = async () => {
    try {
      const r = await api("/api/assistida/encerrar", { execucao_id: sess.execucao_id });
      setResumo(r);
      setSess({ ativa: false });
      setAtualId(null);
      setAguardando(false);
    } catch (e) {
      setMsg(e.message);
    }
  };

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest && e.target.closest("input, textarea, select")) return;
      if (e.code === "Space" || e.key === "ArrowRight") {
        e.preventDefault();
        proximo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [proximo]);

  const salvarRecorte = (valor) => {
    const n = Math.max(0, Math.min(400, Number(valor) || 0));
    setRecorte(n);
    localStorage.setItem("assistida_recorte", String(n));
    if (ext.estado === "ok") enviarExt("configurar", { recorteTopoPx: n });
  };

  // ---------- tela ----------
  // produtos desta sessão cuja última coleta não foi OK (inclui SUSPEITO): aparecem no aviso amarelo até serem refeitos
  const erros = itens.filter((i) => i.coleta && i.coleta.status !== "OK");
  const concluidos = sess?.ativa ? sess.concluidos : 0;
  const total = sess?.ativa ? sess.total : 0;
  const fmtVar = (v) => (v == null ? null : `${v > 0 ? "+" : ""}${String(v).replace(".", ",")}%`);

  return (
    <div className="page">
      {/* aviso fixo no topo: continua à vista enquanto você navega pelo resto da fila e some quando não há mais erro */}
      {sess?.ativa && erros.length > 0 && (
        <div
          role="alert"
          style={{
            position: "sticky", top: 0, zIndex: 20, marginBottom: 12, borderRadius: 12, padding: "10px 16px",
            background: "#fbbf24", color: "#1f1600", boxShadow: "0 6px 24px rgba(0,0,0,0.35)",
          }}
        >
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>
              ⚠ {erros.length} produto(s) com erro: {mostrarErros ? "ocultar" : "ver / refazer"}
            </strong>
            <button
              data-testid="alternar-erros"
              className="btn"
              style={{ background: "#1f1600", color: "#fbbf24", border: "none" }}
              onClick={() => setMostrarErros((v) => !v)}
            >
              {mostrarErros ? "Ocultar" : "Ver erros"}
            </button>
          </div>
          {mostrarErros && (
            <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "grid", gap: 8 }}>
              {erros.map((i) => (
                <li key={i.produto_id} className="row" style={{ justifyContent: "space-between", gap: 12 }}>
                  <span>
                    <strong>{i.nome}</strong> · {i.coleta.status.replaceAll("_", " ")}
                    {i.coleta.detalhe ? <span style={{ opacity: 0.8 }}> ({i.coleta.detalhe})</span> : null}
                  </span>
                  <button
                    data-testid="refazer-erro"
                    className="btn"
                    style={{ background: "#1f1600", color: "#fbbf24", border: "none" }}
                    disabled={!podeNavegar}
                    onClick={() => abrir(i)}
                  >
                    Refazer
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div style={{ fontSize: 12, marginTop: 6, opacity: 0.85 }}>Refazer abre uma página por clique, como no Próximo.</div>
        </div>
      )}

      <section className="hero">
        <span className="eyebrow">Magazine Luiza</span>
        <div className="section-heading">
          <div className="card-title">
            <h1>Coleta assistida</h1>
            <p>Você aperta Próximo, o Chrome abre o produto e o preço e o print aparecem aqui. Uma página por clique.</p>
          </div>
          <div className="toolbar">
            <span className={`chip ${ext.estado === "ok" ? "chip-active" : ""}`}>
              {ext.estado === "procurando" && "Procurando a extensão…"}
              {ext.estado === "ok" && `Extensão conectada (v${ext.versao})`}
              {ext.estado === "ausente" && "Extensão não detectada"}
              {ext.estado === "outro_servidor" && "Extensão configurada para outro servidor"}
            </span>
          </div>
        </div>

        {ext.estado === "outro_servidor" && (
          <div className="card ghost stack mt-2">
            <strong>A extensão aponta para outro servidor</strong>
            <span className="note">
              Servidor configurado na extensão: <code>{ext.servidor}</code>. Abra as opções da extensão (<code>chrome://extensions</code> ou{" "}
              <code>edge://extensions</code> → Detalhes → Opções da extensão), informe o endereço deste site e recarregue esta página.
            </span>
          </div>
        )}
        {ext.estado === "ausente" && (
          <div className="card ghost stack mt-2">
            <strong>Instale a extensão uma vez</strong>
            <span className="note">
              No Chrome, abra <code>chrome://extensions</code>, ligue o <strong>Modo do desenvolvedor</strong>, clique em{" "}
              <strong>Carregar sem compactação</strong> e escolha a pasta <code>extensao</code> do projeto. Depois, recarregue esta página.
            </span>
            <div className="toolbar">
              <button className="btn secondary" onClick={parear}>
                Procurar de novo
              </button>
            </div>
          </div>
        )}
        {msg && <p className="status mt-2">{msg}</p>}
        {foraDaFila.length > 0 && (
          <p className="note mt-2">Ficaram fora da sua fila (em coleta por outra pessoa): {foraDaFila.join(", ")}</p>
        )}
      </section>

      {resumo && (
        <div className="card wide stack">
          <div className="card-title">
            <span className="eyebrow">Execução encerrada</span>
            <h3>
              {resumo.ok} de {resumo.total} com sucesso
            </h3>
          </div>
          <p className="note">
            {resumo.falhas} com falha · {resumo.pulados} pulado(s) · {resumo.em_revisao} aguardando revisão · {resumo.alertas} alerta(s) de preço.
            Os dados já estão nos Relatórios, nas Curvas e nos Prints.
          </p>
        </div>
      )}

      {!sess?.ativa && (
        <div className="card wide stack">
          <div className="card-title">
            <span className="eyebrow">Passo a passo</span>
            <h3>Antes de começar</h3>
          </div>
          <ol className="note" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
            <li>Deixe esta tela num monitor. Ao começar, o Chrome abre uma <strong>janela só da Magalu</strong>: arraste-a para o outro monitor e deixe lá.</li>
            <li>Confira se o resultado preenchido bate com o print e aperte <strong>Próximo</strong> (ou espaço, ou a seta →).</li>
            <li>No fim, <strong>Encerrar</strong> fecha a execução e envia o resumo, se estiver ligado em Alertas.</li>
          </ol>
          {modo === "hospedado" && (
            <p className="note" role="note">
              <strong>Privacidade:</strong> o print sai do <em>seu</em> navegador e fica guardado no servidor da equipe. Se você estiver logado na loja, ele
              pode mostrar seu nome ou CEP. Use um perfil do navegador sem login na loja e/ou o recorte abaixo. Você só coleta os produtos
              atribuídos a você, e o servidor registra quem fez cada captura.
            </p>
          )}
          <label className="row">
            <span className="muted">Cortar do print o topo da página (px), para não mostrar nome ou CEP logados:</span>
            <input type="number" min="0" max="400" style={{ width: 90 }} value={recorte} onChange={(e) => salvarRecorte(e.target.value)} />
          </label>
          <div className="toolbar">
            <button className="btn primary" onClick={iniciar} disabled={ext.estado !== "ok"}>
              Começar coleta assistida
            </button>
          </div>
        </div>
      )}

      {sess?.ativa && (
        <>
          <div className="card wide stack">
            <div className="section-heading">
              <strong>
                {concluidos} de {total} produtos
              </strong>
              <div className="toolbar">
                <button className="btn ghost" onClick={encerrar}>
                  Encerrar
                </button>
              </div>
            </div>
            <div style={{ height: 6, borderRadius: 6, background: "rgba(255,255,255,0.08)" }}>
              <div style={{ height: 6, borderRadius: 6, width: `${total ? (concluidos / total) * 100 : 0}%`, background: "#7c5cff", transition: "width .3s" }} />
            </div>
            <div className="folders">
              {itens.map((i) => (
                <button
                  key={i.produto_id}
                  className={`btn chip ${i.produto_id === atualId ? "chip-active" : ""}`}
                  title={i.coleta ? i.coleta.status : i.pulado ? "pulado" : "pendente"}
                  onClick={() => podeNavegar && abrir(i)}
                  style={{ opacity: i.concluido && i.produto_id !== atualId ? 0.75 : 1 }}
                >
                  <span style={{ color: i.coleta ? STATUS_COR[i.coleta.status] || "#fbbf24" : i.pulado ? "#9aa5b1" : "#64748b" }}>●</span> {i.nome}
                </button>
              ))}
            </div>
          </div>

          <div className="card wide stack" style={{ minHeight: 360 }}>
            {!atual && (
              <div className="stack">
                <h3>Pronto para o primeiro produto</h3>
                <p className="note">Clique em Próximo para abrir {proximoPendente ? <strong>{proximoPendente.nome}</strong> : "o produto"} na janela da Magalu.</p>
              </div>
            )}

            {atual && (
              <>
                <div className="section-heading">
                  <div className="card-title">
                    <span className="eyebrow">
                      {itens.indexOf(atual) + 1} de {total} · {atual.loja}
                    </span>
                    <h2 style={{ margin: 0 }}>{atual.nome}</h2>
                  </div>
                  {resultado && (
                    <span className="chip" style={{ borderColor: STATUS_COR[resultado.status] || "#fbbf24", color: STATUS_COR[resultado.status] || "#fbbf24" }}>
                      {resultado.status.replaceAll("_", " ")}
                    </span>
                  )}
                </div>

                {aguardando && (
                  <div className="stack">
                    <p style={{ fontSize: 20, margin: 0 }}>{etapa && ETAPAS[etapa.etapa] ? ETAPAS[etapa.etapa] : "Aguardando a extensão…"}</p>
                    {etapa && etapa.etapa === "aviso" && <span className="muted">{etapa.detalhe}</span>}
                  </div>
                )}

                {!aguardando && resultado && (
                  <div className="grid-2">
                    <div className="stack">
                      <div>
                        <span className="muted">PIX</span>
                        <div style={{ fontSize: 44, fontWeight: 700, lineHeight: 1.1 }}>{resultado.pix || "—"}</div>
                        {resultado.variacao_pct != null && (
                          <span style={{ color: resultado.variacao_pct < 0 ? "#34d399" : resultado.variacao_pct > 0 ? "#fbbf24" : undefined }}>
                            {fmtVar(resultado.variacao_pct)} <span className="muted">vs {resultado.preco_anterior}</span>
                          </span>
                        )}
                      </div>
                      <div>
                        <span className="muted">Cartão de crédito 1x</span>
                        <div style={{ fontSize: 28, fontWeight: 600 }}>{resultado.cartao_1x || "—"}</div>
                        {!resultado.cartao_1x && resultado.status === "OK" && <span className="muted">Não consegui ler o cartão: abra "opções de pagamento" na janela e use Refazer.</span>}
                      </div>
                      <span className="muted">
                        Vendedor: {resultado.vendedor || "—"} · {resultado.titulo || ""}
                      </span>
                      {EXPLICACAO[resultado.status] && <p className="note" style={{ margin: 0 }}>{EXPLICACAO[resultado.status]}</p>}
                      {resultado.alerta && (
                        <p className="note" style={{ margin: 0 }}>
                          {resultado.alerta.enviado ? "Queda de preço: e-mail de alerta enviado." : `Queda de preço detectada, mas o e-mail não saiu: ${resultado.alerta.erro}`}
                        </p>
                      )}
                    </div>
                    <div className="stack">
                      {resultado.print_url ? (
                        <a href={resultado.print_url} target="_blank" rel="noreferrer">
                          <img src={resultado.print_url} alt="Print da página" style={{ width: "100%", borderRadius: 10, border: "1px solid rgba(255,255,255,0.12)" }} />
                        </a>
                      ) : (
                        <span className="muted">Sem print nesta coleta.</span>
                      )}
                    </div>
                  </div>
                )}

                {avisos.length > 0 && (
                  <div className="stack">
                    {avisos.map((a) => (
                      <p key={a} className="note" style={{ margin: 0, color: "#fbbf24" }}>
                        Aviso: {a}
                      </p>
                    ))}
                  </div>
                )}

                {!aguardando && !resultado && atual.pulado && <p className="note">Produto pulado.</p>}
              </>
            )}

            {/* barra fixa na base da tela: o Próximo fica sempre à vista, sem rolar */}
            <div
              className="toolbar"
              style={{
                marginTop: "auto", position: "sticky", bottom: 0, zIndex: 5, padding: 12, borderRadius: 12,
                background: "rgba(10,16,30,0.94)", backdropFilter: "blur(6px)", border: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <button className="btn primary" style={{ fontSize: 18, padding: "12px 28px" }} onClick={proximo} disabled={!podeProximo}>
                {restamMs > 0 ? `Próximo (${Math.ceil(restamMs / 1000)} s)` : proximoPendente ? "Próximo →" : "Tudo coletado"}
              </button>
              <button className="btn secondary" onClick={() => abrir(atual)} disabled={!atual || !podeNavegar}>
                Refazer
              </button>
              <button className="btn ghost" onClick={pular} disabled={!atual || aguardando || (atual && atual.concluido)}>
                Pular
              </button>
              <button className="btn ghost" onClick={linkQuebrado} disabled={!atual || aguardando}>
                Link quebrado
              </button>
              <span className="muted">Atalho: espaço ou →</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
