import React, { useEffect, useState } from "react";
import { useAuth } from "../auth.jsx";

const MOTIVOS = {
  LINK_QUEBRADO: "Link quebrado",
  PRODUTO_DIVERGENTE: "Produto divergente",
  PRECO_NAO_ENCONTRADO: "Preço não encontrado",
};

const fmtData = (iso) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

export default function Review() {
  const { pode } = useAuth();
  const [itens, setItens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const [manual, setManual] = useState({}); // { [revisaoId]: "link colado" }

  const carregar = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/revisoes");
      const json = await res.json();
      setItens(Array.isArray(json) ? json : []);
    } catch (e) {
      setMsg("Não foi possível carregar as revisões.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  const resolver = async (id, acao, url) => {
    setMsg("");
    try {
      const res = await fetch(`/api/revisoes/${id}/resolver`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ acao, url }),
      });
      const j = await res.json();
      setMsg(res.ok ? (acao === "aprovar" ? "Link atualizado. Vale na próxima coleta." : "Produto desativado.") : j.error || "Falha ao resolver.");
      if (res.ok) {
        carregar();
        window.dispatchEvent(new Event("revisoes-changed")); // atualiza o contador do menu
      }
    } catch (e) {
      setMsg("Erro ao conectar ao servidor.");
    }
  };

  return (
    <div className="page">
      <section className="hero">
        <span className="eyebrow">Links</span>
        <div className="section-heading">
          <div className="card-title">
            <h1>Revisão de links</h1>
            <p>Links que falharam e não puderam ser corrigidos com segurança. Escolha o anúncio certo ou cole um link.</p>
          </div>
          <div className="toolbar">
            <button className="btn secondary" onClick={carregar} disabled={loading}>
              Atualizar
            </button>
          </div>
        </div>
        {msg && <p className="status mt-2">{msg}</p>}
      </section>

      {!loading && itens.length === 0 && (
        <div className="card">
          <p className="muted">Nenhum link aguardando revisão.</p>
        </div>
      )}

      {itens.map((r) => (
        <div key={r.id} className="card wide stack">
          <div className="section-heading">
            <div className="card-title">
              <span className="eyebrow">{MOTIVOS[r.motivo] || r.motivo}</span>
              <h3>{r.produto.nome}</h3>
              <p className="note">
                {r.produto.loja} · desde {fmtData(r.criado_em)}
                {r.ultima_coleta?.erro_detalhe ? ` · ${r.ultima_coleta.erro_detalhe}` : ""}
              </p>
            </div>
            <button className="btn ghost" disabled={!pode("coletor")} onClick={() => window.confirm("Desativar este produto?") && resolver(r.id, "desativar")}>
              Desativar produto
            </button>
          </div>

          <div className="grid-2">
            <div className="stack">
              <strong>Link atual</strong>
              <a href={r.produto.url_atual} target="_blank" rel="noreferrer" style={{ wordBreak: "break-all" }}>
                {r.produto.url_atual}
              </a>
              {r.ultima_coleta?.print_url && (
                <a href={r.ultima_coleta.print_url} target="_blank" rel="noreferrer">
                  <img
                    src={r.ultima_coleta.print_url}
                    alt="Print da falha"
                    style={{ maxWidth: "100%", borderRadius: 8, border: "1px solid var(--border, #ddd)" }}
                  />
                </a>
              )}
            </div>

            <div className="stack">
              <strong>Candidatos sugeridos</strong>
              {r.candidatos.length === 0 && <span className="muted">Nenhum candidato seguro foi encontrado.</span>}
              {r.candidatos.map((c) => (
                <div key={c.url} className="card ghost stack">
                  <span>{c.titulo}</span>
                  <a href={c.url} target="_blank" rel="noreferrer" style={{ wordBreak: "break-all", fontSize: 13 }}>
                    {c.url}
                  </a>
                  <div className="toolbar">
                    <span className="chip chip-active">Confiança {Math.round(c.nota * 100)}%</span>
                    {c.verificado && <span className="chip">Página confirmada</span>}
                    <button className="btn primary" disabled={!pode("coletor")} onClick={() => resolver(r.id, "aprovar", c.url)}>
                      Aprovar este
                    </button>
                  </div>
                </div>
              ))}

              <strong>Colar link manualmente</strong>
              <div className="toolbar">
                <input
                  style={{ flex: 1, minWidth: 220 }}
                  placeholder="https://..."
                  value={manual[r.id] || ""}
                  onChange={(e) => setManual({ ...manual, [r.id]: e.target.value })}
                />
                <button
                  className="btn secondary"
                  disabled={!(manual[r.id] || "").trim()}
                  onClick={() => resolver(r.id, "aprovar", manual[r.id].trim())}
                >
                  Usar este link
                </button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
