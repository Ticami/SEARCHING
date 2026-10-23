import React, { useState, useEffect } from "react";

export default function Links() {
  const [links, setLinks] = useState([]);
  const [novoNome, setNovoNome] = useState("");
  const [novoLink, setNovoLink] = useState("");
  const [novaLoja, setNovaLoja] = useState("");
  const [mensagem, setMensagem] = useState("");

  const carregar = async () => {
    try {
      const res = await fetch("/api/links");
      const data = await res.json();
      if (Array.isArray(data)) {
        setLinks(data);
      } else {
        console.error("Resposta inesperada:", data);
        setLinks([]);
      }
    } catch (err) {
      console.error("Falha ao conectar ao backend:", err);
      setLinks([]);
    }
  };

  const adicionar = async () => {
    if (!novoNome || !novoLink) {
      setMensagem("Preencha todos os campos");
      return;
    }
    try {
      await fetch("/api/links", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nome: novoNome, link: novoLink, loja: novaLoja }),
      });
      setMensagem("Link adicionado!");
      setNovoNome("");
      setNovoLink("");
      setNovaLoja("");
      carregar();
    } catch (e) {
      setMensagem("Falha ao adicionar.");
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  const lojas = ["Magazine Luiza", "Amazon", "Casas Bahia"];

  const inferLoja = (url) => {
    const u = String(url || "").toLowerCase();
    if (u.includes("magazineluiza") || u.includes("magalu")) return "Magazine Luiza";
    if (u.includes("amazon")) return "Amazon";
    if (u.includes("casasbahia")) return "Casas Bahia";
    return "";
  };

  const grupos = {};
  lojas.forEach((l) => {
    grupos[l] = links.filter((x) => (x.LOJA || inferLoja(x.LINK)) === l);
  });

  return (
    <div className="page">
      <div className="card wide">
        <div className="card-header">
          <div className="card-title">
            <span className="eyebrow">Catálogo monitorado</span>
            <h2>Links Monitorados</h2>
          </div>
        </div>

        <div className="card ghost stack">
          <div className="form-inline">
            <input
              type="text"
              placeholder="Nome do produto"
              value={novoNome}
              onChange={(e) => setNovoNome(e.target.value)}
            />
            <input
              type="text"
              placeholder="URL do produto"
              value={novoLink}
              onChange={(e) => setNovoLink(e.target.value)}
            />
            <select value={novaLoja} onChange={(e) => setNovaLoja(e.target.value)}>
              <option value="">Selecione a loja</option>
              {lojas.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
            <button className="btn primary" onClick={adicionar}>
              Adicionar
            </button>
          </div>

          {mensagem && <p className="status">{mensagem}</p>}
        </div>

        {lojas.map((nomeGrupo) => (
          <div key={nomeGrupo} className="table-container links-group" style={{ marginTop: 16 }}>
            <h3>{nomeGrupo}</h3>
            <table>
              <thead>
                <tr>
                  <th>PRODUTO</th>
                  <th>LINK</th>
                  <th>LOJA</th>
                  <th>AÇÕES</th>
                </tr>
              </thead>
              <tbody>
                {grupos[nomeGrupo].map((l, i) => (
                  <RowLink key={`${l.LINK}-${i}`} row={l} onChanged={carregar} />
                ))}
                {grupos[nomeGrupo].length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      Sem links cadastrados
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

function RowLink({ row, onChanged }) {
  const [edit, setEdit] = React.useState(false);
  const [draft, setDraft] = React.useState({
    nome: row["NOME COMERCIAL"],
    link: row.LINK,
    loja: row.LOJA,
  });

  const salvar = async () => {
    const res = await fetch("/api/links", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: row.ID,
        originalNome: row["NOME COMERCIAL"],
        originalLink: row.LINK,
        originalLoja: row.LOJA,
        nome: draft.nome,
        link: draft.link,
        loja: draft.loja,
      }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      window.alert(j.error || "Não foi possível salvar o link.");
      return;
    }
    setEdit(false);
    onChanged();
  };

  const remover = async () => {
    await fetch("/api/links", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: row.ID, nome: row["NOME COMERCIAL"], link: row.LINK, loja: row.LOJA }),
    });
    onChanged();
  };

  return (
    <tr>
      <td>
        {edit ? (
          <input value={draft.nome} onChange={(e) => setDraft({ ...draft, nome: e.target.value })} />
        ) : (
          row["NOME COMERCIAL"]
        )}
      </td>
      <td>
        {edit ? (
          <input value={draft.link} onChange={(e) => setDraft({ ...draft, link: e.target.value })} />
        ) : (
          <a href={row.LINK} target="_blank" rel="noreferrer">
            abrir
          </a>
        )}
      </td>
      <td>
        {edit ? (
          <select value={draft.loja} onChange={(e) => setDraft({ ...draft, loja: e.target.value })}>
            <option>Magazine Luiza</option>
            <option>Amazon</option>
            <option>Casas Bahia</option>
          </select>
        ) : (
          row.LOJA
        )}
      </td>
      <td>
        {edit ? (
          <>
            <button className="btn primary" onClick={salvar}>
              Salvar
            </button>
            <button className="btn ghost" style={{ marginLeft: 6 }} onClick={() => setEdit(false)}>
              Cancelar
            </button>
          </>
        ) : (
          <>
            <button className="btn secondary" onClick={() => setEdit(true)}>
              Editar
            </button>
            <button className="btn ghost" style={{ marginLeft: 6 }} onClick={remover}>
              Remover
            </button>
          </>
        )}
      </td>
    </tr>
  );
}
