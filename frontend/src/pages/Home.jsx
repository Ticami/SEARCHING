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
  const [autoTimes, setAutoTimes] = useState([]);   // ["09:00", "14:30"]
  const [autoDays, setAutoDays] = useState(["mon","tue","wed","thu","fri"]);
  const [autoStores, setAutoStores] = useState({ magalu: true, amazon: false, casasbahia: false });
  const [autoSelecionados, setAutoSelecionados] = useState([]);
  const [timeDraft, setTimeDraft] = useState("");   // "HH:MM"

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
        setAutoEnabled(!!cfg.enabled);
        setAutoTimes(Array.isArray(cfg.times) ? cfg.times : []);
        setAutoDays(Array.isArray(cfg.days) ? cfg.days : ["mon","tue","wed","thu","fri"]);

        // seleções independentes
        const st = cfg.stores || []; // ["magalu","amazon"]
        setAutoStores({
          magalu: st.includes("magalu") || st.includes("magazineluiza"),
          amazon: st.includes("amazon") || st.includes("amazon.com.br"),
          casasbahia: st.includes("casasbahia")
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
    setAutoDays((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]
    );
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
        stores: selectedDomains,          // seleção EXCLUSIVA do automático
        include: autoSelecionados,        // modelos EXCLUSIVOS do automático
      };

      const r = await fetch("/api/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      setStatus(j.message || "Agendamento salvo!");
    } catch (e) {
      setStatus("Erro ao salvar agendamento");
    }
  };

  return (
    <div className="page">
      {/* ======= BLOCO MANUAL ======= */}
      <div className="hero">
        <div>
          <h1>SEARCHING</h1>
          <p>Monitoramento automatizado de preços e captura de prints.</p>
          <div className="hero-actions">
            {/* lojas (manual) */}
            <div className="filters" style={{ marginBottom: 8 }}>
              <label>
                <input
                  type="checkbox"
                  checked={stores.magalu}
                  onChange={(e) => setStores({ ...stores, magalu: e.target.checked })}
                />
                <span style={{ marginLeft: 6 }}>Magazine Luiza</span>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={stores.amazon}
                  onChange={(e) => setStores({ ...stores, amazon: e.target.checked })}
                />
                <span style={{ marginLeft: 6 }}>Amazon</span>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={stores.casasbahia}
                  onChange={(e) => setStores({ ...stores, casasbahia: e.target.checked })}
                />
                <span style={{ marginLeft: 6 }}>Casas Bahia</span>
              </label>
            </div>

            {/* modelos (manual) */}
            <div
              className="card"
              style={{ padding: 12, background: "#121821", border: "1px solid #263041" }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <button className="btn" onClick={() => setOpenModelos((v) => !v)}>
                  Modelos {openModelos ? "▾" : "▸"}
                </button>
                <div>
                  <button className="btn" onClick={() => setSelecionados(modelos)}>
                    Selecionar todos
                  </button>
                  <button
                    className="btn"
                    style={{ marginLeft: 6 }}
                    onClick={() => setSelecionados([])}
                  >
                    Limpar
                  </button>
                </div>
              </div>
              {openModelos && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                    gap: 8,
                    maxHeight: 180,
                    overflow: "auto",
                    marginTop: 8,
                  }}
                >
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
              <div className="muted" style={{ marginTop: 6 }}>
                Se nenhum modelo for marcado, todos serão considerados.
              </div>
            </div>

            <button className="btn primary" onClick={iniciarMonitoramento} disabled={loading}>
              {loading ? "Executando..." : "Iniciar monitoramento"}
            </button>
          </div>
          {status && <p className="status mt-2">{status}</p>}
        </div>
      </div>

      {/* ======= BLOCO AUTOMÁTICO ======= */}
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Modo Automático (agendar horários)</h3>

        {/* Seleções exclusivas do automático */}
        <div className="filters" style={{ marginTop: 8 }}>
          <strong style={{ marginRight: 8 }}>Lojas (automático):</strong>
          <label>
            <input
              type="checkbox"
              checked={autoStores.magalu}
              onChange={(e) => setAutoStores({ ...autoStores, magalu: e.target.checked })}
            />
            <span style={{ marginLeft: 6 }}>Magazine Luiza</span>
          </label>
          <label>
            <input
              type="checkbox"
              checked={autoStores.amazon}
              onChange={(e) => setAutoStores({ ...autoStores, amazon: e.target.checked })}
            />
            <span style={{ marginLeft: 6 }}>Amazon</span>
          </label>
          <label>
            <input
              type="checkbox"
              checked={autoStores.casasbahia}
              onChange={(e) => setAutoStores({ ...autoStores, casasbahia: e.target.checked })}
            />
            <span style={{ marginLeft: 6 }}>Casas Bahia</span>
          </label>
        </div>

        {/* Modelos do automático */}
        <div className="card" style={{ marginTop: 12, padding: 12, background: "#121821", border: "1px solid #263041" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Modelos (automático)</strong>
            <div>
              <button className="btn" onClick={() => setAutoSelecionados(modelos)}>Selecionar todos</button>
              <button className="btn" style={{ marginLeft: 6 }} onClick={() => setAutoSelecionados([])}>Limpar</button>
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 8,
              maxHeight: 160,
              overflow: "auto",
              marginTop: 8,
            }}
          >
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
          <div className="muted" style={{ marginTop: 6 }}>
            Se nenhum modelo for marcado, todos serão considerados no automático.
          </div>
        </div>

        {/* Linha superior: toggle do agendamento */}
        <div className="filters" style={{ marginTop: 12 }}>
          <label>
            <input
              type="checkbox"
              checked={autoEnabled}
              onChange={(e) => setAutoEnabled(e.target.checked)}
            />
            <span style={{ marginLeft: 6 }}>Ativar agendamento automático</span>
          </label>
        </div>

        {/* Horários + dias */}
        <div className="grid-2" style={{ marginTop: 8 }}>
          <div className="card" style={{ background: "#121821", border: "1px solid #263041" }}>
            <strong>Horários do dia (24h)</strong>
            <div className="filters" style={{ marginTop: 8 }}>
              <input
                type="time"
                value={timeDraft}
                onChange={(e) => setTimeDraft(e.target.value)}
              />
              <button className="btn" onClick={addTime}>Adicionar horário</button>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
              {autoTimes.map((t) => (
                <span key={t} className="chip" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {t}
                  <button className="icon-btn" onClick={() => removeTime(t)}>×</button>
                </span>
              ))}
              {autoTimes.length === 0 && <div className="muted">Nenhum horário adicionado</div>}
            </div>
          </div>

          <div className="card" style={{ background: "#121821", border: "1px solid #263041" }}>
            <strong>Dias da semana</strong>
            <div className="filters" style={{ marginTop: 8 }}>
              {[
                ["sun","Dom"],["mon","Seg"],["tue","Ter"],["wed","Qua"],["thu","Qui"],["fri","Sex"],["sat","Sáb"]
              ].map(([key,label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={autoDays.includes(key)}
                    onChange={() => toggleDay(key)}
                  />
                  <span style={{ marginLeft: 6 }}>{label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={salvarAgendamento}>Salvar agendamento</button>
          <span className="muted" style={{ marginLeft: 10 }}>
            O backend executará a coleta automaticamente nos horários/dias definidos.
          </span>
        </div>
      </div>

      {/* Cards informativos que você já tinha */}
      <div className="card grid-2 mt-4">
        <div>
          <h3>Relatórios</h3>
          <p>Consulte o histórico de coletas, preços e status.</p>
        </div>
        <div>
          <h3>Prints</h3>
          <p>Visualize e baixe as imagens capturadas por execução.</p>
        </div>
      </div>
    </div>
  );
}
