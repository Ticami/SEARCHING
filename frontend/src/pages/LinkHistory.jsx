import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth.jsx";

const fmtData = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const ORIGEM = { manual: "Manual", automatico: "Automática (recuperação)" };

export default function LinkHistory() {
  const { pode } = useAuth();
  const [itens, setItens] = useState([]);
  const [msg, setMsg] = useState("");
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const res = await fetch("/api/links/historico");
      const json = await res.json();
      setItens(Array.isArray(json) ? json : []);
    } catch {
      setMsg("Não foi possível carregar o histórico.");
    }
    setCarregando(false);
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const reverter = async (item) => {
    if (!window.confirm(`Voltar o link de "${item.produto}" para o endereço anterior?`)) return;
    const res = await fetch(`/api/links/historico/${item.id}/reverter`, { method: "POST" });
    const json = await res.json().catch(() => ({}));
    setMsg(res.ok ? json.message : json.error || "Não foi possível reverter.");
    if (res.ok) carregar();
  };

  return (
    <div className="page">
      <section className="hero">
        <span className="eyebrow">Links</span>
        <div className="section-heading">
          <div className="card-title">
            <h1>Histórico de trocas de link</h1>
            <p>Toda troca de endereço de um produto, manual ou feita sozinha pela recuperação de links, com a possibilidade de voltar atrás.</p>
          </div>
          <div className="toolbar">
            <Link className="btn secondary" to="/links">Voltar para Links</Link>
          </div>
        </div>
        {msg && <p className="status mt-2" role="status">{msg}</p>}
      </section>

      <div className="card wide stack">
        <div style={{ overflowX: "auto" }} role="region" aria-label="Trocas de link" tabIndex={0}>
          <table className="table">
            <caption className="muted" style={{ textAlign: "left" }}>Trocas de link, da mais recente para a mais antiga</caption>
            <thead>
              <tr>
                <th scope="col">Quando</th>
                <th scope="col">Produto</th>
                <th scope="col">Origem</th>
                <th scope="col">Link antigo</th>
                <th scope="col">Link novo</th>
                <th scope="col">Confiança</th>
                <th scope="col"><span className="sr-only">Ações</span></th>
              </tr>
            </thead>
            <tbody>
              {itens.map((h) => (
                <tr key={h.id}>
                  <td>{fmtData(h.em)}</td>
                  <td>{h.produto}</td>
                  <td>{ORIGEM[h.origem] || h.origem}{h.motivo ? ` · ${h.motivo}` : ""}</td>
                  <td style={{ maxWidth: 260, overflowWrap: "anywhere" }}><a href={h.url_antiga} target="_blank" rel="noreferrer noopener">{h.url_antiga}</a></td>
                  <td style={{ maxWidth: 260, overflowWrap: "anywhere" }}><a href={h.url_nova} target="_blank" rel="noreferrer noopener">{h.url_nova}</a></td>
                  <td>{h.nota_confianca != null ? `${Math.round(h.nota_confianca * 100)}%` : "—"}</td>
                  <td>
                    <button
                      className="btn secondary"
                      onClick={() => reverter(h)}
                      aria-label={`Reverter a troca de link de ${h.produto} feita em ${fmtData(h.em)}`}
                      disabled={!h.revertivel || !pode("admin")}
                      title={h.revertivel ? "Voltar ao link antigo" : "O produto já usa outro link: só a troca mais recente pode ser revertida"}
                    >
                      Reverter
                    </button>
                  </td>
                </tr>
              ))}
              {!carregando && itens.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">Nenhuma troca de link registrada ainda.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
