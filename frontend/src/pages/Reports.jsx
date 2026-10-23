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

  const [datasSelecionadas, setDatasSelecionadas] = useState([]);
  const [modelosSelecionados, setModelosSelecionados] = useState([]);
  const [lojasSelecionadas, setLojasSelecionadas] = useState([]);
  const [entreguesSelecionados, setEntreguesSelecionados] = useState([]);
  const [de, setDe] = useState(""); // período: AAAA-MM-DD
  const [ate, setAte] = useState("");
  const [editingIndex, setEditingIndex] = useState(null);
  const [draftLink, setDraftLink] = useState("");
  const [salvandoLink, setSalvandoLink] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");

  const [filterOpen, setFilterOpen] = useState(null);
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

  const inferLoja = (url) => {
    const u = String(url || "").toLowerCase();
    if (u.includes("magazineluiza") || u.includes("magalu")) return "Magazine Luiza";
    if (u.includes("amazon")) return "Amazon";
    if (u.includes("casasbahia")) return "Casas Bahia";
    return "";
  };

  const isErroBusca = (d) => {
    const modelo = (d.MODELO || "").trim().toLowerCase();
    const pixRaw = (d.PIX || "").trim().toLowerCase();
    const credRaw = (d.CARTAO_DE_CREDITO || d.CREDITO || d.PARCELADO || "").trim().toLowerCase();
    const modeloErro = ["oops", "oops!", "ops", "ops!", "erro"].includes(modelo);
    const precoErro = ["n/a", "na", ""].includes(pixRaw) && ["n/a", "na", ""].includes(credRaw);
    return modeloErro || precoErro;
  };

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

    const dataMatch = datasSelecionadas.length === 0 || datasSelecionadas.includes(dataRaw);
    const modeloMatch = modelosSelecionados.length === 0 || modelosSelecionados.includes(modeloAtual);
    const lojaMatch = lojasSelecionadas.length === 0 || lojasSelecionadas.includes(lojaAtual);
    const entregueMatch = entreguesSelecionados.length === 0 || entreguesSelecionados.includes(entregueAtual);
    const periodoMatch = (!de || dataRaw >= de) && (!ate || dataRaw <= ate);

    return dataMatch && modeloMatch && lojaMatch && entregueMatch && periodoMatch;
  });

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

  const normMoney = (s) => (s || "").replace(/\s+/g, " ").replace(" ,", ",").trim();

  const abrirEdicao = (idx, item) => {
    setEditingIndex(idx);
    setDraftLink(item.LINK || "");
    setStatusMsg("");
  };

  const cancelarEdicao = () => {
    setEditingIndex(null);
    setDraftLink("");
    setStatusMsg("");
  };

  const salvarLink = async (item) => {
    if (!draftLink.trim()) {
      setStatusMsg("Informe um link valido.");
      return;
    }
    setSalvandoLink(true);
    setStatusMsg("");
    try {
      const payload = {
        id: item.PRODUTO_ID,
        originalNome: item.NOME || item.MODELO,
        originalLink: item.LINK,
        originalLoja: siteFrom(item),
        nome: item.NOME || item.MODELO,
        link: draftLink.trim(),
        loja: inferLoja(draftLink) || siteFrom(item),
      };
      const res = await fetch("/api/links", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatusMsg("Link atualizado.");
      setEditingIndex(null);
      setDraftLink("");
      carregar();
    } catch (err) {
      console.error("Erro ao salvar link:", err);
      setStatusMsg("Falha ao salvar o link. Tente novamente.");
    } finally {
      setSalvandoLink(false);
    }
  };

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
      if (cols.CREDITO) row.CARTAO_DE_CREDITO = normMoney(d.CARTAO_DE_CREDITO || d.CREDITO || d.PARCELADO || "");
      return row;
    });

    const esc = (v) => `"${String(v).replaceAll('"', '""')}"`;
    const csv = [head.join(";"), ...rows.map((r) => head.map((h) => esc(r[h] ?? "")).join(";"))].join("\r\n");
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

  // Excel gerado pelo servidor: preços numéricos e caminho do print, só das linhas filtradas.
  const exportarExcel = async () => {
    const ids = filtrados.map((d) => d.ID).filter(Boolean);
    if (ids.length === 0) {
      setStatusMsg("Nenhuma linha para exportar.");
      return;
    }
    try {
      const res = await fetch("/api/historico/exportar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setStatusMsg(j.error || "Falha ao exportar.");
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `relatorio_${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      setStatusMsg(`${ids.length} linha(s) exportada(s).`);
    } catch (e) {
      setStatusMsg("Erro ao exportar para Excel.");
    }
  };

  const renderFilterMenu = (tipo, valores, selecionados, setSelecionados, labelFn) => {
    if (filterOpen !== tipo) return null;
    return (
      <div ref={filterRef} className="filter-menu card ghost stack">
        <div className="section-heading">
          <strong>Filtrar {tipo.replace("_", " ")}</strong>
          <button className="icon-btn" onClick={() => setFilterOpen(null)}>
            ×
          </button>
        </div>
        <div className="toolbar">
          <button className="btn ghost" onClick={() => setSelecionados(valores)}>
            Selecionar todos
          </button>
          <button className="btn ghost" onClick={() => setSelecionados([])}>
            Limpar
          </button>
        </div>
        <div className="stack" style={{ maxHeight: 220, overflow: "auto" }}>
          {valores.map((v) => {
            const checked = selecionados.includes(v);
            return (
              <label key={v} className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) =>
                    setSelecionados((prev) => (e.target.checked ? [...prev, v] : prev.filter((x) => x !== v)))
                  }
                />
                <span>{labelFn ? labelFn(v) : v}</span>
              </label>
            );
          })}
          {valores.length === 0 && <span className="muted">Nenhum valor disponível</span>}
        </div>
      </div>
    );
  };

  return (
    <div className="page">
      <div className="card wide">
        <div className="card-header">
          <div className="card-title">
            <span className="eyebrow">Dados consolidados</span>
            <h2>Relatórios</h2>
          </div>
          <div className="toolbar">
            <button className="btn" onClick={carregar}>
              Atualizar
            </button>
            <button className="btn" onClick={exportarCSV}>
              Exportar CSV
            </button>
            <button className="btn primary" onClick={exportarExcel}>
              Exportar Excel
            </button>
          </div>
        </div>
        {statusMsg && <p className="status">{statusMsg}</p>}

        <div className="card ghost stack" style={{ marginBottom: 12 }}>
          <div className="toolbar">
            <span className="muted" style={{ fontSize: 13 }}>
              Período
            </span>
            <input type="date" value={de} max={ate || undefined} onChange={(e) => setDe(e.target.value)} />
            <span className="muted">até</span>
            <input type="date" value={ate} min={de || undefined} onChange={(e) => setAte(e.target.value)} />
            {(de || ate) && (
              <button
                className="btn ghost"
                onClick={() => {
                  setDe("");
                  setAte("");
                }}
              >
                Limpar período
              </button>
            )}
          </div>
          <p className="note">Ative/desative as colunas que deseja ver/exportar.</p>
          <div className="toolbar">
            {Object.keys(cols).map((k) => (
              <label key={k} className="chip">
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
                  <th className="th-filter">
                    <div className="row">
                      <span>DATA</span>
                      <button
                        className="icon-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setFilterOpen(filterOpen === "DATA" ? null : "DATA");
                        }}
                      >
                        ▼
                      </button>
                    </div>
                    {renderFilterMenu("DATA", datas, datasSelecionadas, setDatasSelecionadas, (d) => formatDateBR(d))}
                  </th>
                )}

                {cols.MODELO && (
                  <th className="th-filter">
                    <div className="row">
                      <span>MODELO</span>
                      <button
                        className="icon-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setFilterOpen(filterOpen === "MODELO" ? null : "MODELO");
                        }}
                      >
                        ▼
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
                    <th className="th-filter">
                      <div className="row">
                        <span>LOJA</span>
                        <button
                          className="icon-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFilterOpen(filterOpen === "LOJA" ? null : "LOJA");
                          }}
                        >
                          ▼
                        </button>
                      </div>
                      {renderFilterMenu("LOJA", lojas, lojasSelecionadas, setLojasSelecionadas)}
                    </th>

                    <th className="th-filter">
                      <div className="row">
                        <span>ENTREGUE POR</span>
                        <button
                          className="icon-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFilterOpen(filterOpen === "ENTREGUE_POR" ? null : "ENTREGUE_POR");
                          }}
                        >
                          ▼
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
              {filtrados.map((item, i) => {
                const erro = isErroBusca(item);
                const editando = editingIndex === i;
                const nomeMostrar = erro ? item.NOME || item.MODELO : item.MODELO || item.NOME;
                const creditoValor = normMoney(item.CARTAO_DE_CREDITO || item.CREDITO || item.PARCELADO);
                return (
                  <tr key={i}>
                    {cols.DATA && <td>{formatDateBR(item.DATA)}</td>}
                    {cols.MODELO && <td>{nomeMostrar}</td>}
                    {cols.LOJA && (
                      <>
                        <td>{siteFrom(item)}</td>
                        <td>{item.ENTREGUE_POR || ""}</td>
                      </>
                    )}
                    {cols.PIX && <td className="price">{erro ? (item.STATUS && item.STATUS !== "OK" ? item.STATUS.replaceAll("_", " ") : "Erro") : normMoney(item.PIX)}</td>}
                    {cols.CREDITO && (
                      <td className="price">
                        {editando ? (
                          <div className="stack" style={{ gap: 6 }}>
                            <input
                              value={draftLink}
                              onChange={(e) => setDraftLink(e.target.value)}
                              placeholder="Cole o novo link do produto"
                            />
                            <div className="row" style={{ gap: 6 }}>
                              <button className="btn primary" onClick={() => salvarLink(item)} disabled={salvandoLink}>
                                Salvar
                              </button>
                              <button className="btn ghost" onClick={cancelarEdicao} disabled={salvandoLink}>
                                Cancelar
                              </button>
                            </div>
                          </div>
                        ) : erro ? (
                          <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                            <span>Erro</span>
                            <button className="btn secondary" onClick={() => abrirEdicao(i, item)}>
                              Editar link
                            </button>
                          </div>
                        ) : (
                          creditoValor
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
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
