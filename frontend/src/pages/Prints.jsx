import React, { useEffect, useState } from "react";

export default function Prints() {
  const [pastas, setPastas] = useState([]);
  const [imagens, setImagens] = useState([]);
  const [selecionada, setSelecionada] = useState("");
  const [modalImg, setModalImg] = useState("");
  const [mes, setMes] = useState("");
  const [ano, setAno] = useState("");

  const carregarPastas = async () => {
    try {
      const res = await fetch("/api/prints-list");
      const json = await res.json();
      setPastas(json);
    } catch (err) {
      console.error("Erro ao carregar pastas:", err);
    }
  };

  const carregarImagens = async (pasta) => {
    try {
      const res = await fetch(`/api/prints-list/${pasta}`);
      const imgs = await res.json();
      setImagens(imgs);
      setSelecionada(pasta);
    } catch {
      setImagens([]);
    }
  };

  useEffect(() => {
    carregarPastas();
  }, []);

  const parsePastaDate = (p) => {
    const m = /^([0-9]{4})-([0-9]{2})-([0-9]{2})_([0-9]{2})-([0-9]{2})-([0-9]{2})$/.exec(p);
    if (!m) return null;
    const [_, yy, mm, dd, hh, mi] = m;
    return { y: Number(yy), m: Number(mm), d: Number(dd), hh: Number(hh), mi: Number(mi) };
  };

  const labelBR = (p) => {
    const d = parsePastaDate(p);
    if (!d) return p;
    const yy2 = String(d.y).slice(-2);
    const dd = String(d.d).padStart(2, "0");
    const mm = String(d.m).padStart(2, "0");
    const hh = String(d.hh).padStart(2, "0");
    const mi = String(d.mi).padStart(2, "0");
    return `${dd}/${mm}/${yy2} ${hh}:${mi}`;
  };

  const anosDisponiveis = Array.from(new Set(pastas.map((p) => parsePastaDate(p)?.y).filter(Boolean))).sort(
    (a, b) => b - a
  );

  const pastasFiltradas = pastas.filter((p) => {
    const d = parsePastaDate(p);
    if (!d) return true;
    const condMes = mes ? d.m === Number(mes) : true;
    const condAno = ano ? d.y === Number(ano) : true;
    return condMes && condAno;
  });

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

  const imgUrl = (pasta, img) => `/api/prints/${pasta}/${img}`;
  const deviceNameFromFilename = (filename) => {
    if (!filename) return "";
    const base = filename.replace(/\.(png|jpe?g)$/i, "");
    const timeMatch = base.match(/(.+)_\d{2}-\d{2}-\d{2}$/);
    const rawName = timeMatch ? timeMatch[1] : base;
    return rawName.replace(/_/g, " ").trim();
  };

  return (
    <div className="page">
      <div className="card wide">
        <div className="card-header">
          <div className="card-title">
            <span className="eyebrow">Galeria</span>
            <h2>Prints</h2>
          </div>
        </div>

        <div className="toolbar" style={{ marginBottom: 12 }}>
          <select value={mes} onChange={(e) => setMes(e.target.value)}>
            <option value="">Mês (todos)</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select value={ano} onChange={(e) => setAno(e.target.value)}>
            <option value="">Ano (todos)</option>
            {anosDisponiveis.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        <div className="folders">
          {pastas.length === 0 && <p>Nenhuma coleta encontrada.</p>}
          {pastasFiltradas.map((p, i) => (
            <button
              key={i}
              className={`btn chip ${p === selecionada ? "chip-active" : ""}`}
              onClick={() => carregarImagens(p)}
            >
              {labelBR(p)}
            </button>
          ))}
        </div>

        {selecionada && (
          <div className="gallery">
            <div className="gallery-header">
              <h3>{labelBR(selecionada)}</h3>
              <span className="muted">{imagens.length} imagem(ns)</span>
            </div>
            <div className="gallery-grid">
              {imagens.map((img, i) => (
                <figure key={i} className="thumb">
                  <div className="thumb-title" title={deviceNameFromFilename(img)}>
                    {deviceNameFromFilename(img)}
                  </div>
                  <img src={imgUrl(selecionada, img)} alt={img} onClick={() => setModalImg(imgUrl(selecionada, img))} />
                  <figcaption className="thumb-actions">
                    <a href={imgUrl(selecionada, img)} download>
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
