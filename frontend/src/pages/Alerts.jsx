import React, { useEffect, useState } from "react";
import { useAuth } from "../auth.jsx";

const BASES_PRECO = { pix: "PIX", cartao_1x: "Cartão 1x" };
const BASES_COMPARACAO = {
  ultimo: "Último preço válido",
  minimo_n_dias: "Menor preço dos últimos N dias",
  media_n_dias: "Média dos últimos N dias",
};

const fmtData = (iso) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

async function chamar(url, metodo, corpo) {
  const res = await fetch(url, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  return { ok: res.ok, json };
}

export default function Alerts() {
  const { pode } = useAuth();
  const [dados, setDados] = useState(null);
  const [regras, setRegras] = useState([]);
  const [cfg, setCfg] = useState({});
  const [msg, setMsg] = useState("");
  const [testando, setTestando] = useState(false);

  const carregar = async () => {
    try {
      const [a, r] = await Promise.all([fetch("/api/alertas"), fetch("/api/alertas/regras")]);
      const dadosJson = await a.json();
      setDados(dadosJson);
      setCfg(dadosJson.config || {});
      const regrasJson = await r.json();
      setRegras(Array.isArray(regrasJson) ? regrasJson : []);
    } catch (e) {
      setMsg("Não foi possível carregar os alertas.");
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  const salvarConfig = async () => {
    setMsg("");
    const { ok, json } = await chamar("/api/alertas/config", "PUT", cfg);
    setMsg(ok ? json.message : json.error || "Falha ao salvar.");
    if (ok) setCfg(json.config);
  };

  const testarEmail = async () => {
    setTestando(true);
    setMsg("");
    const { json } = await chamar("/api/alertas/teste", "POST");
    setMsg(json.message || "Sem resposta do servidor.");
    setTestando(false);
    carregar();
  };

  const editarRegra = (id, campo, valor) =>
    setRegras((prev) => prev.map((r) => (r.produto_id === id ? { ...r, [campo]: valor } : r)));

  const salvarRegra = async (r) => {
    setMsg("");
    const { ok, json } = await chamar(`/api/alertas/regras/${r.produto_id}`, "PUT", {
      alerta_pct: r.alerta_pct,
      alerta_base: r.alerta_base,
      alerta_preco_alvo: r.alerta_preco_alvo,
    });
    setMsg(ok ? `Regra de ${r.nome} salva.` : json.error || "Falha ao salvar a regra.");
  };

  const smtp = dados?.smtp;

  return (
    <div className="page">
      <section className="hero">
        <span className="eyebrow">Monitoramento</span>
        <div className="section-heading">
          <div className="card-title">
            <h1>Alertas de preço</h1>
            <p>Receba um e-mail, com o print da página, quando o preço cair.</p>
          </div>
          <div className="toolbar">
            <button className="btn primary" onClick={testarEmail} disabled={testando || !smtp?.configurado || !pode("admin")}>
              {testando ? "Enviando..." : "Enviar e-mail de teste"}
            </button>
          </div>
        </div>
        {msg && <p className="status mt-2">{msg}</p>}
      </section>

      {/* ===== E-mail ===== */}
      <div className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">E-mail</span>
          <h3>{smtp?.configurado ? "Configurado" : "Não configurado"}</h3>
        </div>
        {smtp?.configurado ? (
          <p className="note">
            Envia de <strong>{smtp.remetente}</strong> para <strong>{smtp.destinatarios.join(", ")}</strong> via {smtp.servidor}.
          </p>
        ) : (
          <>
            <p className="note">{smtp?.motivo}</p>
            <p className="note">
              Copie <code>.env.example</code> para <code>.env</code> na raiz do projeto e preencha. No Gmail, use uma{" "}
              <strong>senha de app</strong> (exige verificação em duas etapas). As credenciais ficam só no seu computador.
            </p>
          </>
        )}
      </div>

      {/* ===== Regras globais ===== */}
      <div className="card wide stack">
        <div className="section-heading">
          <div className="card-title">
            <span className="eyebrow">Regras</span>
            <h3>Padrão para todos os produtos</h3>
          </div>
          <label className="row">
            <input
              type="checkbox"
              checked={cfg.alertas_ativos === "1"}
              onChange={(e) => setCfg({ ...cfg, alertas_ativos: e.target.checked ? "1" : "0" })}
            />
            <span>Alertas ativos</span>
          </label>
        </div>

        <div className="grid-2">
          <label className="stack">
            <span>Queda mínima para avisar (%)</span>
            <input value={cfg.alerta_pct_queda ?? ""} onChange={(e) => setCfg({ ...cfg, alerta_pct_queda: e.target.value })} />
          </label>
          <label className="stack">
            <span>Queda adicional para novo aviso do mesmo produto (%)</span>
            <input value={cfg.alerta_degrau_pct ?? ""} onChange={(e) => setCfg({ ...cfg, alerta_degrau_pct: e.target.value })} />
          </label>
          <label className="stack">
            <span>Preço considerado</span>
            <select value={cfg.alerta_base_preco || "pix"} onChange={(e) => setCfg({ ...cfg, alerta_base_preco: e.target.value })}>
              {Object.entries(BASES_PRECO).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            <span>Comparar com</span>
            <select
              value={cfg.alerta_base_comparacao || "ultimo"}
              onChange={(e) => setCfg({ ...cfg, alerta_base_comparacao: e.target.value })}
            >
              {Object.entries(BASES_COMPARACAO).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            <span>N (dias) das comparações por menor preço / média</span>
            <input value={cfg.alerta_dias_janela ?? ""} onChange={(e) => setCfg({ ...cfg, alerta_dias_janela: e.target.value })} />
          </label>
          <label className="row">
            <input
              type="checkbox"
              checked={cfg.resumo_diario_email === "1"}
              onChange={(e) => setCfg({ ...cfg, resumo_diario_email: e.target.checked ? "1" : "0" })}
            />
            <span>Enviar e-mail de resumo ao fim de cada coleta</span>
          </label>
        </div>

        <div className="toolbar">
          <button className="btn primary" onClick={salvarConfig} disabled={!pode("admin")}>
            Salvar padrão
          </button>
        </div>
        <div className="note">
          Só coletas válidas geram alerta. Leituras suspeitas ou com falha são ignoradas, e o mesmo preço não é avisado duas vezes.
        </div>
      </div>

      {/* ===== Regras por produto ===== */}
      <div className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">Regras</span>
          <h3>Exceções por produto</h3>
          <p className="note">Deixe em branco para usar o padrão acima.</p>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Produto</th>
                <th>Queda mín. (%)</th>
                <th>Comparar com</th>
                <th>Avisar abaixo de (R$)</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {regras.map((r) => (
                <tr key={r.produto_id}>
                  <td>{r.nome}</td>
                  <td>
                    <input
                      style={{ width: 80 }}
                      value={r.alerta_pct ?? ""}
                      onChange={(e) => editarRegra(r.produto_id, "alerta_pct", e.target.value)}
                    />
                  </td>
                  <td>
                    <select value={r.alerta_base || ""} onChange={(e) => editarRegra(r.produto_id, "alerta_base", e.target.value)}>
                      <option value="">Padrão</option>
                      {Object.entries(BASES_COMPARACAO).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      style={{ width: 110 }}
                      placeholder="opcional"
                      value={r.alerta_preco_alvo ?? ""}
                      onChange={(e) => editarRegra(r.produto_id, "alerta_preco_alvo", e.target.value)}
                    />
                  </td>
                  <td>
                    <button className="btn secondary" onClick={() => salvarRegra(r)} disabled={!pode("coletor")}>
                      Salvar
                    </button>
                  </td>
                </tr>
              ))}
              {regras.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    Nenhum produto ativo.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ===== Registro ===== */}
      <div className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">Registro</span>
          <h3>Alertas enviados</h3>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Produto</th>
                <th>Anterior</th>
                <th>Atual</th>
                <th>Queda</th>
                <th>Situação</th>
              </tr>
            </thead>
            <tbody>
              {(dados?.alertas || []).map((a) => (
                <tr key={a.id}>
                  <td>{fmtData(a.enviado_em)}</td>
                  <td>{a.produto}</td>
                  <td>{a.preco_anterior}</td>
                  <td className="price">{a.preco_atual}</td>
                  <td>{a.queda_pct > 0 ? `-${String(a.queda_pct).replace(".", ",")}%` : "—"}</td>
                  <td title={a.erro || a.destinatario}>
                    {a.sucesso ? `Enviado para ${a.destinatario}` : `Não enviado: ${a.erro || "erro desconhecido"}`}
                  </td>
                </tr>
              ))}
              {dados && dados.alertas.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    Nenhum alerta ainda.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
