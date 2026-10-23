import React, { useEffect, useMemo, useState } from "react";
import { LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts";

export default function Curves() {
  const [dados, setDados] = useState([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState("");

  const [modeloSelecionado, setModeloSelecionado] = useState("");
  const [lojaSelecionada, setLojaSelecionada] = useState("TODAS");
  const [de, setDe] = useState(""); // período: AAAA-MM-DD
  const [ate, setAte] = useState("");

  const simplifyModelo = (s) => {
    if (!s) return s;
    const m = String(s).match(/(.{3,}?\b\d{2,4}\s*GB\b)/i);
    return m ? m[1].trim() : String(s).split(",")[0].split(" - ")[0].trim();
  };

  const parseMoneyBR = (s) => {
    if (!s) return null;
    const txt = String(s);
    if (txt.toUpperCase().includes("N/A")) return null;
    let limpo = txt.replace(/[^\d,]/g, "");
    if (!limpo) return null;
    limpo = limpo.replace(/\./g, "").replace(",", ".");
    const v = Number(limpo);
    return Number.isNaN(v) ? null : v;
  };

  const formatDateBR = (s) => {
    if (!s) return "";
    const [date] = String(s).split(" ");
    const [y, m, d] = date.split("-");
    if (!y || !m || !d) return s;
    return `${d}/${m}/${y}`;
  };

  const parseDate = (s) => {
    if (!s) return new Date(0);
    const [date, time] = String(s).split(" ");
    const [y, m, d] = date.split("-").map(Number);
    const [hh = 0, mm = 0, ss = 0] = (time || "").split(":").map(Number);
    return new Date(y, (m || 1) - 1, d || 1, hh, mm, ss);
  };

  useEffect(() => {
    const carregar = async () => {
      try {
        setLoading(true);
        setErro("");
        const res = await fetch("/api/historico");
        const json = await res.json();
        if (!Array.isArray(json)) {
          setErro("Resposta inesperada do backend.");
          setDados([]);
          return;
        }
        setDados(json);
      } catch (e) {
        console.error(e);
        setErro("Erro ao carregar histórico.");
        setDados([]);
      } finally {
        setLoading(false);
      }
    };
    carregar();
  }, []);

  const modelos = useMemo(() => {
    const nomes = dados.map((d) => d.NOME || d.MODELO || "").filter((x) => x && x.trim() !== "");
    const uniq = Array.from(new Set(nomes.map(simplifyModelo)));
    return uniq.sort((a, b) => a.localeCompare(b));
  }, [dados]);

  const lojas = useMemo(() => {
    const nomes = dados.map((d) => d.SITE || d.LOJA || "").filter((x) => x && x.trim() !== "");
    const uniq = Array.from(new Set(nomes));
    return uniq.sort((a, b) => a.localeCompare(b));
  }, [dados]);

  const dataChart = useMemo(() => {
    if (!dados.length) return [];

    const modeloBase = modeloSelecionado || (modelos.length ? modelos[0] : "");

    const filtrados = dados
      .filter((d) => {
        const modeloBruto = d.NOME || d.MODELO || "";
        if (d.STATUS && d.STATUS !== "OK") return false; // leituras suspeitas ou com falha não entram na curva
        const dia = (d.DATA || "").split(" ")[0];
        if ((de && dia < de) || (ate && dia > ate)) return false;
        const modeloSimples = simplifyModelo(modeloBruto);
        if (modeloSimples !== modeloBase) return false;

        if (lojaSelecionada !== "TODAS") {
          const loja = d.SITE || d.LOJA || "";
          if (loja !== lojaSelecionada) return false;
        }
        return true;
      })
      .map((d) => {
        const pixRaw = d.PIX;
        const credRaw = d.CARTAO_DE_CREDITO || d.CREDITO || d.PARCELADO || d.PARCELADO_1X;

        return {
          dataLabel: formatDateBR(d.DATA),
          dataSort: parseDate(d.DATA).getTime(),
          loja: d.SITE || d.LOJA || "",
          pix: d.PIX_CENTAVOS != null ? d.PIX_CENTAVOS / 100 : parseMoneyBR(pixRaw),
          credito: d.CREDITO_CENTAVOS != null ? d.CREDITO_CENTAVOS / 100 : parseMoneyBR(credRaw),
        };
      })
      .filter((r) => r.pix != null || r.credito != null)
      .sort((a, b) => a.dataSort - b.dataSort);

    return filtrados;
  }, [dados, modeloSelecionado, lojaSelecionada, modelos, de, ate]);

  const modeloMostrando = modeloSelecionado || (modelos.length ? modelos[0] : "");

  return (
    <div className="page">
      <div className="card wide">
        <div className="card-header">
          <div className="card-title">
            <span className="eyebrow">Tendências</span>
            <h2>Curvas de Preço</h2>
          </div>
        </div>

        <div className="card ghost">
          <div className="toolbar">
            <div>
              <label className="input-label">Modelo</label>
              <select value={modeloSelecionado || modeloMostrando} onChange={(e) => setModeloSelecionado(e.target.value)}>
                {modelos.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="input-label">Loja</label>
              <select value={lojaSelecionada} onChange={(e) => setLojaSelecionada(e.target.value)}>
                <option value="TODAS">Todas as lojas</option>
                {lojas.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="input-label">De</label>
              <input type="date" value={de} max={ate || undefined} onChange={(e) => setDe(e.target.value)} />
            </div>

            <div>
              <label className="input-label">Até</label>
              <input type="date" value={ate} min={de || undefined} onChange={(e) => setAte(e.target.value)} />
            </div>
          </div>
        </div>

        {loading && <p className="muted">Carregando histórico...</p>}
        {erro && <p className="status error">{erro}</p>}

        {!loading && !erro && !dataChart.length && <p className="muted">Nenhum dado encontrado para esse modelo/loja.</p>}

        {!loading && !erro && dataChart.length > 0 && (
          <div className="card ghost" style={{ marginTop: 12 }}>
            <div style={{ width: "100%", height: 420 }}>
              <ResponsiveContainer>
                <LineChart data={dataChart} margin={{ top: 16, right: 32, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="dataLabel" stroke="#75839d" />
                  <YAxis stroke="#75839d" />
                  <Tooltip
                    formatter={(value, name) => {
                      if (value == null) return ["-", name];
                      return [
                        value.toLocaleString("pt-BR", {
                          style: "currency",
                          currency: "BRL",
                        }),
                        name === "pix" ? "PIX" : "Cartão (1x)",
                      ];
                    }}
                    labelFormatter={(label) => `Data: ${label}`}
                  />
                  <Legend formatter={(value) => (value === "pix" ? "PIX" : "Cartão (1x)")} />
                  <Line type="monotone" dataKey="pix" stroke="#82ca9d" dot={{ r: 3 }} name="pix" connectNulls />
                  <Line type="monotone" dataKey="credito" stroke="#8884d8" dot={{ r: 3 }} name="credito" connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {!loading && !erro && dataChart.length > 0 && (
          <div className="card ghost" style={{ marginTop: 12 }}>
            <h4>Resumo rápido</h4>
            <p className="muted">
              Modelo: <strong>{modeloMostrando}</strong>{" "}
              {lojaSelecionada !== "TODAS" && (
                <>
                  | Loja: <strong>{lojaSelecionada}</strong>
                </>
              )}
            </p>
            <p className="muted">
              Pontos na curva: <strong>{dataChart.length}</strong>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
