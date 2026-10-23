import React, { useEffect, useState } from "react";

const fmtDia = (iso) => {
  const [y, m, d] = String(iso).split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
};

const fmtHora = (iso) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";

export default function Prints() {
  const [modo, setModo] = useState("data"); // "data" | "produto"
  const [datas, setDatas] = useState([]);
  const [produtos, setProdutos] = useState([]);
  const [dataSel, setDataSel] = useState("");
  const [produtoSel, setProdutoSel] = useState("");
  const [itens, setItens] = useState([]);
  const [carregando, setCarregando] = useState(false);
  const [modalImg, setModalImg] = useState("");

  useEffect(() => {
    fetch("/api/prints-galeria")
      .then((r) => r.json())
      .then((j) => setDatas(Array.isArray(j.datas) ? j.datas : []))
      .catch(() => setDatas([]));
    fetch("/api/links")
      .then((r) => r.json())
      .then((j) => setProdutos(Array.isArray(j) ? j : []))
      .catch(() => setProdutos([]));
  }, []);

  const carregar = async (query) => {
    setCarregando(true);
    try {
      const res = await fetch(`/api/prints-galeria?${query}`);
      const j = await res.json();
      setItens(Array.isArray(j.itens) ? j.itens : []);
    } catch {
      setItens([]);
    } finally {
      setCarregando(false);
    }
  };

  const escolherData = (d) => {
    setDataSel(d);
    carregar(`data=${encodeURIComponent(d)}`);
  };

  const escolherProduto = (id) => {
    setProdutoSel(id);
    if (id) carregar(`produto_id=${id}`);
    else setItens([]);
  };

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") setModalImg("");
    };
    if (modalImg) {
      window.addEventListener("keydown", onKey);
      document.body.style.overflow = "hidden";
    }
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "auto";
    };
  }, [modalImg]);

  const trocarModo = (m) => {
    setModo(m);
    setItens([]);
    setDataSel("");
    setProdutoSel("");
  };

  return (
    <div className="page">
      <div className="card wide">
        <div className="card-header">
          <div className="card-title">
            <span className="eyebrow">Galeria</span>
            <h2>Prints</h2>
          </div>
          <div className="toolbar">
            <button className={`btn chip ${modo === "data" ? "chip-active" : ""}`} onClick={() => trocarModo("data")}>
              Por data
            </button>
            <button className={`btn chip ${modo === "produto" ? "chip-active" : ""}`} onClick={() => trocarModo("produto")}>
              Por produto
            </button>
          </div>
        </div>

        {modo === "data" && (
          <div className="folders">
            {datas.length === 0 && <p>Nenhuma coleta com print encontrada.</p>}
            {datas.map((d) => (
              <button
                key={d.data}
                className={`btn chip ${d.data === dataSel ? "chip-active" : ""}`}
                onClick={() => escolherData(d.data)}
              >
                {fmtDia(d.data)} · {d.com_print}
              </button>
            ))}
          </div>
        )}

        {modo === "produto" && (
          <div className="toolbar" style={{ marginBottom: 12 }}>
            <select value={produtoSel} onChange={(e) => escolherProduto(e.target.value)}>
              <option value="">Escolha um produto</option>
              {produtos.map((p) => (
                <option key={p.ID} value={p.ID}>
                  {p["NOME COMERCIAL"]}
                </option>
              ))}
            </select>
          </div>
        )}

        {(dataSel || produtoSel) && (
          <div className="gallery">
            <div className="gallery-header">
              <h3>{modo === "data" ? fmtDia(dataSel) : produtos.find((p) => String(p.ID) === String(produtoSel))?.["NOME COMERCIAL"]}</h3>
              <span className="muted">{carregando ? "Carregando..." : `${itens.length} print(s)`}</span>
            </div>
            <div className="gallery-grid">
              {itens.map((it) => (
                <figure key={it.id} className="thumb">
                  <div className="thumb-title" title={it.produto}>
                    {modo === "data" ? it.produto : fmtHora(it.coletado_em)}
                  </div>
                  <img src={it.print_url} alt={it.produto} onClick={() => setModalImg(it.print_url)} />
                  <figcaption className="thumb-actions" style={{ display: "block" }}>
                    <div>{it.pix ? <strong>PIX {it.pix}</strong> : <span className="muted">Sem preço</span>}</div>
                    {it.cartao_1x && <div className="muted">Cartão 1x {it.cartao_1x}</div>}
                    <div className="muted" style={{ fontSize: 12 }}>
                      {modo === "data" ? fmtHora(it.coletado_em) : null}
                      {it.status !== "OK" ? ` ${modo === "data" ? "· " : ""}${it.status.replaceAll("_", " ")}` : ""}
                    </div>
                    <a href={it.print_url} download>
                      Baixar
                    </a>
                  </figcaption>
                </figure>
              ))}
            </div>
          </div>
        )}

        {modalImg && (
          <div className="modal" onClick={() => setModalImg("")}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <button className="icon-btn close" aria-label="Fechar" onClick={() => setModalImg("")}>
                ×
              </button>
              <img src={modalImg} alt="Visualização" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
