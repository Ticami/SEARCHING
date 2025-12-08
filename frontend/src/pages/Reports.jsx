import React, { useState, useEffect, useMemo, useRef } from "react";

export default function Reports() {
  const [dados, setDados] = useState([]);
  const [cols, setCols] = useState({
    DATA: true,
    MODELO: true,
    LOJA: true,
    PIX: true,
    CREDITO: true,
  });

  // filtros "estilo Excel"
  const [datasSelecionadas, setDatasSelecionadas] = useState([]);
  const [modelosSelecionados, setModelosSelecionados] = useState([]);
  const [lojasSelecionadas, setLojasSelecionadas] = useState([]);
  const [entreguesSelecionados, setEntreguesSelecionados] = useState([]);

  const [filterOpen, setFilterOpen] = useState(null); // "DATA" | "MODELO" | "LOJA" | "ENTREGUE_POR" | null
  const filterRef = useRef(null);

  const carregar = async () => {
    try {
      const res = await fetch("/api/historico");
      const json = await res.json();
      if (!Array.isArray(json)) {
        console.error("Resposta inesperada de /api/historico:", json);
        setDados([]);
        return;
      }
      setDados(json.reverse());
    } catch (e) {
      console.error("Erro ao carregar histórico", e);
      setDados([]);
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  const siteFrom = (d) => d.LOJA || d.SITE || "";

  const lojas = useMemo(
    () =>
      Array.from(
        new Set(
          dados
            .map((d) => siteFrom(d))
            .filter(Boolean)
        )
      ).sort(),
    [dados]
  );

  const modelos = useMemo(
    () =>
      Array.from(
        new Set(
          dados
            .map((d) => (d.MODELO || d.NOME || "").trim())
            .filter(Boolean)
        )
      ).sort(),
    [dados]
  );

  const datas = useMemo(
    () =>
      Array.from(
        new Set(
          dados
            .map((d) => (d.DATA || "").split(" ")[0])
            .filter(Boolean)
        )
      ).sort().reverse(),
    [dados]
  );

  const entregues = useMemo(
    () =>
      Array.from(
        new Set(
          dados
            .map((d) => (d.ENTREGUE_POR || "").trim())
            .filter(Boolean)
        )
      ).sort(),
    [dados]
  );

  const filtrados = dados.filter((d) => {
    const modeloAtual = (d.MODELO || d.NOME || "").trim();
    const lojaAtual = siteFrom(d);
    const entregueAtual = (d.ENTREGUE_POR || "").trim();
    const dataRaw = (d.DATA || "").split(" ")[0];

    const dataMatch =
      datasSelecionadas.length === 0 || datasSelecionadas.includes(dataRaw);
    const modeloMatch =
      modelosSelecionados.length === 0 ||
      modelosSelecionados.includes(modeloAtual);
    const lojaMatch =
      lojasSelecionadas.length === 0 || lojasSelecionadas.includes(lojaAtual);
    const entregueMatch =
      entreguesSelecionados.length === 0 ||
      entreguesSelecionados.includes(entregueAtual);

    return dataMatch && modeloMatch && lojaMatch && entregueMatch;
  });

  // fecha pop-up clicando fora
  useEffect(() => {
    const onClick = (e) => {
      if (!filterRef.current) return;
      if (!filterRef.current.contains(e.target)) {
        setFilterOpen(null);
      }
    };
    if (filterOpen) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [filterOpen]);

  const simplifyModelo = (s) => {
    if (!s) return s;
    const m = s.match(/^(.*?\b\d{2,4}\s*GB\b)/i);
    if (m) return m[1].trim();
    return s.split(/[,|\-]/)[0].trim();
  };

  const formatDateBR = (s) => {
    if (!s) return "";
    const [date] = String(s).split(" ");
    const [y, m, d] = date.split("-");
    if (!y || !m || !d) return s;
    return `${d}-${m}-${y}`;
  };

  const normMoney = (s) =>
    (s || "").replace(/\s+/g, " ").replace(" ,", ",").trim();

  const exportarCSV = () => {
    if (filtrados.length === 0) return;
    const head = [];
    if (cols.DATA) head.push("DATA");
    if (cols.MODELO) head.push("MODELO");
    if (cols.LOJA) {
      head.push("LOJA");
      head.push("ENTREGUE_POR");
    }
    if (cols.PIX) head.push("PIX");
    if (cols.CREDITO) head.push("CARTAO_DE_CREDITO");

    const rows = filtrados.map((d) => {
      const row = {};
      if (cols.DATA) row.DATA = formatDateBR(d.DATA);
      if (cols.MODELO) row.MODELO = d.MODELO || d.NOME || "";
      if (cols.LOJA) {
        row.LOJA = siteFrom(d);
        row.ENTREGUE_POR = d.ENTREGUE_POR || "";
      }
      if (cols.PIX) row.PIX = normMoney(d.PIX);
      if (cols.CREDITO)
        row.CARTAO_DE_CREDITO = normMoney(
          d.CARTAO_DE_CREDITO || d.CREDITO || ""
        );
      return row;
    });

    const esc = (v) => `"${String(v).replaceAll('"', '""')}"`;
    const csv = [
      head.join(";"),
      ...rows.map((r) => head.map((h) => esc(r[h] ?? "")).join(";")),
    ].join("\r\n");
    const blob = new Blob(["\ufeff" + csv], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `relatorio_filtrado_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // helper para desenhar menu de filtro estilo Excel
  const renderFilterMenu = (
    tipo,
    valores,
    selecionados,
    setSelecionados,
    labelFn
  ) => {
    if (filterOpen !== tipo) return null;
    return (
      <div
        ref={filterRef}
        className="card"
        style={{
          position: "absolute",
          top: "100%",
          left: 0,
          marginTop: 4,
          zIndex: 30,
          minWidth: 240,
          background: "#0f1722",
          border: "1px solid #263041",
          padding: 8,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 6,
          }}
        >
          <strong>Filtrar {tipo.replace("_", " ")}</strong>
          <button className="icon-btn" onClick={() => setFilterOpen(null)}>
            ×
          </button>
        </div>
        <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
          <button className="btn" onClick={() => setSelecionados(valores)}>
            Selecionar todos
          </button>
          <button className="btn" onClick={() => setSelecionados([])}>
            Limpar
          </button>
        </div>
        <div
          style={{
            maxHeight: 220,
            overflow: "auto",
            display: "grid",
            gap: 4,
          }}
        >
          {valores.map((v) => {
            const checked = selecionados.includes(v);
            return (
              <label
                key={v}
                style={{ display: "flex", alignItems: "center", gap: 6 }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) =>
                    setSelecionados((prev) =>
                      e.target.checked
                        ? [...prev, v]
                        : prev.filter((x) => x !== v)
                    )
                  }
                />
                <span>{labelFn ? labelFn(v) : v}</span>
              </label>
            );
          })}
          {valores.length === 0 && (
            <span className="muted">Nenhum valor disponível</span>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="page">
      <div className="card wide">
        <div className="card-header">
          <h2>Relatórios</h2>
          <div className="filters" style={{ gap: 8 }}>
            <button className="btn" onClick={carregar}>
              Atualizar
            </button>
            <button className="btn primary" onClick={exportarCSV}>
              Exportar CSV
            </button>
          </div>
        </div>

        {/* toggle de colunas (mantido) */}
        <div className="card" style={{ marginBottom: 12 }}>
          <div className="filters">
            {Object.keys(cols).map((k) => (
              <label
                key={k}
                style={{ display: "flex", alignItems: "center", gap: 6 }}
              >
                <input
                  type="checkbox"
                  checked={cols[k]}
                  onChange={(e) =>
                    setCols({
                      ...cols,
                      [k]: e.target.checked,
                    })
                  }
                />
                <span>{k}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                {cols.DATA && (
                  <th style={{ position: "relative" }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                    >
                      <span>DATA</span>
                      <button
                        className="icon-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setFilterOpen(
                            filterOpen === "DATA" ? null : "DATA"
                          );
                        }}
                      >
                        ▾
                      </button>
                    </div>
                    {renderFilterMenu(
                      "DATA",
                      datas,
                      datasSelecionadas,
                      setDatasSelecionadas,
                      (d) => formatDateBR(d)
                    )}
                  </th>
                )}

                {cols.MODELO && (
                  <th style={{ position: "relative" }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                    >
                      <span>MODELO</span>
                      <button
                        className="icon-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setFilterOpen(
                            filterOpen === "MODELO" ? null : "MODELO"
                          );
                        }}
                      >
                        ▾
                      </button>
                    </div>
                    {renderFilterMenu(
                      "MODELO",
                      modelos,
                      modelosSelecionados,
                      setModelosSelecionados,
                      (m) => simplifyModelo(m)
                    )}
                  </th>
                )}

                {cols.LOJA && (
                  <>
                    <th style={{ position: "relative" }}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <span>LOJA</span>
                        <button
                          className="icon-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFilterOpen(
                              filterOpen === "LOJA" ? null : "LOJA"
                            );
                          }}
                        >
                          ▾
                        </button>
                      </div>
                      {renderFilterMenu(
                        "LOJA",
                        lojas,
                        lojasSelecionadas,
                        setLojasSelecionadas
                      )}
                    </th>

                    <th style={{ position: "relative" }}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <span>ENTREGUE POR</span>
                        <button
                          className="icon-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFilterOpen(
                              filterOpen === "ENTREGUE_POR"
                                ? null
                                : "ENTREGUE_POR"
                            );
                          }}
                        >
                          ▾
                        </button>
                      </div>
                      {renderFilterMenu(
                        "ENTREGUE_POR",
                        entregues,
                        entreguesSelecionados,
                        setEntreguesSelecionados
                      )}
                    </th>
                  </>
                )}

                {cols.PIX && <th>PIX</th>}
                {cols.CREDITO && <th>CARTÃO DE CRÉDITO</th>}
              </tr>
            </thead>

            <tbody>
              {filtrados.map((item, i) => (
                <tr key={i}>
                  {cols.DATA && <td>{formatDateBR(item.DATA)}</td>}
                  {cols.MODELO && <td>{item.MODELO || item.NOME}</td>}
                  {cols.LOJA && (
                    <>
                      <td>{siteFrom(item)}</td>
                      <td>{item.ENTREGUE_POR || ""}</td>
                    </>
                  )}
                  {cols.PIX && (
                    <td className="price">{normMoney(item.PIX)}</td>
                  )}
                  {cols.CREDITO && (
                    <td className="price">
                      {normMoney(item.CARTAO_DE_CREDITO || item.CREDITO)}
                    </td>
                  )}
                </tr>
              ))}
              {filtrados.length === 0 && (
                <tr>
                  <td
                    colSpan={
                      (cols.DATA ? 1 : 0) +
                      (cols.MODELO ? 1 : 0) +
                      (cols.LOJA ? 2 : 0) +
                      (cols.PIX ? 1 : 0) +
                      (cols.CREDITO ? 1 : 0)
                    }
                    className="muted"
                  >
                    Nenhum registro encontrado com os filtros atuais.
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

