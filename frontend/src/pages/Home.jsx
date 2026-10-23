import React, { useEffect, useState } from "react";

export default function Home() {
  // ====== MANUAL (como já estava) ======
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [stores, setStores] = useState({ magalu: true, amazon: false, casasbahia: false });
  const [modelos, setModelos] = useState([]);
  const [selecionados, setSelecionados] = useState([]);
  const [openModelos, setOpenModelos] = useState(true);

  // ====== AUTOMÁTICO (seleções separadas) ======
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [autoTimes, setAutoTimes] = useState([]); // ["09:00", "14:30"]
  const [autoDays, setAutoDays] = useState(["mon", "tue", "wed", "thu", "fri"]);
  const [autoStores, setAutoStores] = useState({ magalu: true, amazon: false, casasbahia: false });
  const [autoSelecionados, setAutoSelecionados] = useState([]);
  const [timeDraft, setTimeDraft] = useState(""); // "HH:MM"
  const [agenda, setAgenda] = useState(null); // { tarefa, ultima_execucao, comando }

  const fmtData = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
      ? "—"
      : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  };

  const fmtDuracao = (s) => {
    if (s == null) return "";
    return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
  };

  // =========================
  // Carrega modelos do backend
  // =========================
  useEffect(() => {
    const carregarModelos = async () => {
      try {
        const res = await fetch("/api/links");
        const json = await res.json();

        if (!Array.isArray(json)) return;

        const nomes = json
          .map((item) => item["NOME COMERCIAL"] || item["NOME"] || "")
          .filter((n) => n.trim() !== "");

        const simp = (s) => {
          if (!s) return s;
          const m = String(s).match(/(.{3,}?\b\d{2,4}\s*GB\b)/i);
          return m ? m[1].trim() : String(s).split(",")[0].split(" - ")[0].trim();
        };

        const uniq = Array.from(new Set(nomes.map(simp)));
        setModelos(uniq);
      } catch (err) {
        console.error("Erro ao carregar modelos:", err);
      }
    };
    carregarModelos();
  }, []);

  // =========================
  // Carrega/agenda automática
  // =========================
  useEffect(() => {
    const loadSchedule = async () => {
      try {
        const r = await fetch("/api/schedule");
        const j = await r.json();
        const cfg = j?.config || {};
        setAgenda(j);
        setAutoEnabled(!!cfg.enabled);
        setAutoTimes(Array.isArray(cfg.times) ? cfg.times : []);
        setAutoDays(Array.isArray(cfg.days) ? cfg.days : ["mon", "tue", "wed", "thu", "fri"]);

        // seleções independentes
        const st = cfg.stores || []; // ["magalu","amazon"]
        setAutoStores({
          magalu: st.includes("magalu") || st.includes("magazineluiza"),
          amazon: st.includes("amazon") || st.includes("amazon.com.br"),
          casasbahia: st.includes("casasbahia"),
        });

        setAutoSelecionados(Array.isArray(cfg.include) ? cfg.include : []);
      } catch (e) {
        console.warn("Não foi possível carregar /api/schedule", e);
      }
    };
    loadSchedule();
  }, []);

  // =========================
  // MANUAL: iniciar coleta
  // =========================
  const iniciarMonitoramento = async () => {
    setLoading(true);
    setStatus("Iniciando monitoramento...");
    try {
      const selectedDomains = [
        ...(stores.magalu ? ["magalu", "magazineluiza"] : []),
        ...(stores.amazon ? ["amazon.com.br", "amazon"] : []),
        ...(stores.casasbahia ? ["casasbahia"] : []),
      ];
      const payload = {
        stores: selectedDomains,
        include: selecionados,
        exclude: [],
      };

      const res = await fetch("/api/coletar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setStatus(data.msg || data.message || data.error || "Monitoramento concluído!");
    } catch (err) {
      setStatus("Erro ao conectar ao servidor");
    } finally {
      setLoading(false);
    }
  };

  // =========================
  // AUTOMÁTICO: helpers
  // =========================
  const toggleDay = (d) => {
    setAutoDays((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]));
  };

  const addTime = () => {
    const t = (timeDraft || "").trim();
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t)) return;
    setAutoTimes((prev) => Array.from(new Set([...prev, t])).sort());
    setTimeDraft("");
  };

  const removeTime = (t) => {
    setAutoTimes((prev) => prev.filter((x) => x !== t));
  };

  const salvarAgendamento = async () => {
    try {
      const selectedDomains = [
        ...(autoStores.magalu ? ["magalu", "magazineluiza"] : []),
        ...(autoStores.amazon ? ["amazon.com.br", "amazon"] : []),
        ...(autoStores.casasbahia ? ["casasbahia"] : []),
      ];

      const body = {
        enabled: autoEnabled,
        times: autoTimes,
        days: autoDays,
        stores: selectedDomains, // seleção EXCLUSIVA do automático
        include: autoSelecionados, // modelos EXCLUSIVOS do automático
      };

      const r = await fetch("/api/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (j.tarefa) setAgenda(j);
      setStatus(j.message || "Agendamento salvo!");
    } catch (e) {
      setStatus("Erro ao salvar agendamento");
    }
  };

  return (
    <div className="page">
      <section className="hero">
        <span className="eyebrow">Monitoramento</span>
        <div className="section-heading">
          <div className="card-title">
            <h1>SEARCHING</h1>
            <p>Monitoramento automatizado de preços e captura de prints.</p>
          </div>
          <div className="toolbar">
            <button className="btn primary" onClick={iniciarMonitoramento} disabled={loading}>
              {loading ? "Executando..." : "Iniciar monitoramento"}
            </button>
          </div>
        </div>

        <div className="stack">
          <div className="toolbar">
            <label className="chip">
              <input
                type="checkbox"
                checked={stores.magalu}
                onChange={(e) => setStores({ ...stores, magalu: e.target.checked })}
              />
              <span>Magazine Luiza</span>
            </label>
            <label className="chip">
              <input
                type="checkbox"
                checked={stores.amazon}
                onChange={(e) => setStores({ ...stores, amazon: e.target.checked })}
              />
              <span>Amazon</span>
            </label>
            <label className="chip">
              <input
                type="checkbox"
                checked={stores.casasbahia}
                onChange={(e) => setStores({ ...stores, casasbahia: e.target.checked })}
              />
              <span>Casas Bahia</span>
            </label>
          </div>

          <div className="card ghost stack">
            <div className="section-heading">
              <div className="card-title">
                <span className="eyebrow">Modo Manual</span>
                <h3>Modelos monitorados</h3>
              </div>
              <div className="toolbar">
                <button className="btn secondary" onClick={() => setOpenModelos((v) => !v)}>
                  Modelos {openModelos ? "▼" : "▶"}
                </button>
                <button className="btn ghost" onClick={() => setSelecionados(modelos)}>
                  Selecionar todos
                </button>
                <button className="btn ghost" onClick={() => setSelecionados([])}>
                  Limpar
                </button>
              </div>
            </div>

            {openModelos && (
              <div className="option-grid">
                {modelos.map((m) => {
                  const checked = selecionados.includes(m);
                  return (
                    <label key={m} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setSelecionados((prev) => {
                            if (e.target.checked) return [...prev, m];
                            return prev.filter((x) => x !== m);
                          });
                        }}
                      />
                      <span>{m}</span>
                    </label>
                  );
                })}
              </div>
            )}
            <div className="note">Se nenhum modelo for marcado, todos serão considerados.</div>
          </div>
        </div>
        {status && <p className="status mt-2">{status}</p>}
      </section>

      {/* ======= BLOCO AUTOMÁTICO ======= */}
      <div className="card wide">
        <div className="section-heading">
          <div className="card-title">
            <span className="eyebrow">Modo Automático</span>
            <h3>Agendar horários</h3>
            <p className="note">Seleções independentes das do modo manual.</p>
          </div>
          <label className="row">
            <input type="checkbox" checked={autoEnabled} onChange={(e) => setAutoEnabled(e.target.checked)} />
            <span>Ativar agendamento automático</span>
          </label>
        </div>

        <div className="stack">
          {agenda && (
            <div className="card ghost grid-2">
              <div className="stack">
                <strong>Tarefa do Windows</strong>
                <span>
                  {agenda.tarefa?.instalada
                    ? agenda.tarefa.ativa
                      ? "Instalada e ativa"
                      : "Instalada, mas desativada"
                    : "Ainda não instalada"}
                </span>
                <span className="muted">
                  Próxima execução: {agenda.tarefa?.ativa ? fmtData(agenda.tarefa.proxima_execucao) : "—"}
                </span>
              </div>
              <div className="stack">
                <strong>Última execução</strong>
                {agenda.ultima_execucao ? (
                  <>
                    <span>
                      {fmtData(agenda.ultima_execucao.iniciada_em)}
                      {agenda.ultima_execucao.em_andamento
                        ? " (em andamento)"
                        : agenda.ultima_execucao.duracao_s != null
                        ? ` · ${fmtDuracao(agenda.ultima_execucao.duracao_s)}`
                        : ""}
                    </span>
                    <span className="muted">
                      {agenda.ultima_execucao.ok} de {agenda.ultima_execucao.total} com sucesso ·{" "}
                      {agenda.ultima_execucao.falhas} com falha · origem: {agenda.ultima_execucao.origem}
                    </span>
                  </>
                ) : (
                  <span className="muted">Nenhuma execução registrada</span>
                )}
              </div>
            </div>
          )}

          <div className="toolbar">
            <span className="muted" style={{ fontSize: 13 }}>
              Lojas (automático)
            </span>
            <label className="chip">
              <input
                type="checkbox"
                checked={autoStores.magalu}
                onChange={(e) => setAutoStores({ ...autoStores, magalu: e.target.checked })}
              />
              <span>Magazine Luiza</span>
            </label>
            <label className="chip">
              <input
                type="checkbox"
                checked={autoStores.amazon}
                onChange={(e) => setAutoStores({ ...autoStores, amazon: e.target.checked })}
              />
              <span>Amazon</span>
            </label>
            <label className="chip">
              <input
                type="checkbox"
                checked={autoStores.casasbahia}
                onChange={(e) => setAutoStores({ ...autoStores, casasbahia: e.target.checked })}
              />
              <span>Casas Bahia</span>
            </label>
          </div>

          <div className="card ghost stack">
            <div className="section-heading">
              <strong>Modelos (automático)</strong>
              <div className="toolbar">
                <button className="btn ghost" onClick={() => setAutoSelecionados(modelos)}>
                  Selecionar todos
                </button>
                <button className="btn ghost" onClick={() => setAutoSelecionados([])}>
                  Limpar
                </button>
              </div>
            </div>
            <div className="option-grid slim">
              {modelos.map((m) => {
                const checked = autoSelecionados.includes(m);
                return (
                  <label key={m} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        setAutoSelecionados((prev) => {
                          if (e.target.checked) return [...prev, m];
                          return prev.filter((x) => x !== m);
                        });
                      }}
                    />
                    <span>{m}</span>
                  </label>
                );
              })}
            </div>
            <div className="note">Se nenhum modelo for marcado, todos serão considerados no automático.</div>
          </div>

          <div className="grid-2">
            <div className="card ghost">
              <strong>Horários do dia (24h)</strong>
              <div className="toolbar" style={{ marginTop: 8 }}>
                <input type="time" value={timeDraft} onChange={(e) => setTimeDraft(e.target.value)} />
                <button className="btn secondary" onClick={addTime}>
                  Adicionar horário
                </button>
              </div>
              <div className="folders mt-2">
                {autoTimes.map((t) => (
                  <span key={t} className="chip">
                    {t}
                    <button className="icon-btn" onClick={() => removeTime(t)}>
                      ×
                    </button>
                  </span>
                ))}
                {autoTimes.length === 0 && <div className="muted">Nenhum horário adicionado</div>}
              </div>
            </div>

            <div className="card ghost">
              <strong>Dias da semana</strong>
              <div className="toolbar" style={{ marginTop: 8 }}>
                {[
                  ["sun", "Dom"],
                  ["mon", "Seg"],
                  ["tue", "Ter"],
                  ["wed", "Qua"],
                  ["thu", "Qui"],
                  ["fri", "Sex"],
                  ["sat", "Sáb"],
                ].map(([key, label]) => (
                  <label key={key} className="chip">
                    <input type="checkbox" checked={autoDays.includes(key)} onChange={() => toggleDay(key)} />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="section-heading">
            <div className="note">
              Ao salvar, a tarefa é criada no Agendador de Tarefas do Windows e roda mesmo com o sistema fechado. O
              computador precisa estar ligado e com o usuário logado; se estiver desligado no horário, a coleta roda
              assim que possível.
            </div>
            <button className="btn primary" onClick={salvarAgendamento}>
              Salvar agendamento
            </button>
          </div>
        </div>
      </div>

      {/* Cards informativos que você já tinha */}
      <div className="card grid-2 mt-4">
        <div className="stack">
          <h3>Relatórios</h3>
          <p>Consulte o histórico de coletas, preços e status.</p>
        </div>
        <div className="stack">
          <h3>Prints</h3>
          <p>Visualize e baixe as imagens capturadas por execução.</p>
        </div>
      </div>
    </div>
  );
}
