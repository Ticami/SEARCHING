import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth.jsx";

// ---------- conteúdo explicativo ----------
const PASSOS = [
  {
    titulo: "Cadastre os links",
    texto:
      "Em Links você informa o nome do produto e o endereço do anúncio em cada loja. O sistema entende marca, modelo, armazenamento e variantes (FE, Ultra, +), e usa isso para conferir se a página aberta é mesmo o produto certo.",
    para: "/links",
    acao: "Abrir Links",
  },
  {
    titulo: "Colete os preços",
    texto:
      "Na Magazine Luiza use a Coleta assistida: você aperta Próximo, o Chrome abre o produto e a extensão lê PIX, cartão 1x e tira o print. Nas lojas que aceitam robô, a coleta automática abre o Chrome sozinha.",
    para: "/assisted",
    acao: "Coleta assistida",
  },
  {
    titulo: "O sistema confere",
    texto:
      "Cada coleta recebe um status. Só vale como preço se o título bate com o cadastro e o valor faz sentido: uma variação grande demais vira SUSPEITO e não gera alerta.",
    para: "#status",
    acao: "Ver os status",
  },
  {
    titulo: "Corrija o que falhou",
    texto:
      "Link quebrado? O sistema procura o anúncio novo e só troca sozinho quando tem certeza de que é o mesmo produto. Na dúvida, o link vai para a Revisão, com o print e candidatos para você escolher.",
    para: "/review",
    acao: "Abrir Revisão",
  },
  {
    titulo: "Acompanhe e receba alertas",
    texto:
      "Relatórios, Curvas e Prints mostram o histórico com o preço de cada dia e a prova em imagem. Quando o preço cai, um e-mail chega com o print anexado.",
    para: "/reports",
    acao: "Abrir Relatórios",
  },
];

const STATUS = [
  ["OK", "#34d399", "Preço lido e conferido.", "Nada a fazer."],
  ["SUSPEITO", "#fbbf24", "O preço mudou mais de 40% desde a última coleta válida.", "Confira o print. Não gera alerta."],
  ["BLOQUEIO", "#f87171", "A loja recusou o acesso (erro 403 ou verificação).", "Registrado com o print. Nada é forçado."],
  ["LINK QUEBRADO", "#f87171", "O endereço não leva mais a uma página de produto.", "Entra na Revisão de links."],
  ["PRODUTO DIVERGENTE", "#fb923c", "A página é de outro produto ou variante (ex.: Ultra no lugar do normal).", "Confira o link em Links ou na Revisão."],
  ["PREÇO NÃO ENCONTRADO", "#fb923c", "A página abriu, mas o preço não apareceu.", "Use Refazer. Se repetir, o layout da loja mudou."],
  ["INDISPONÍVEL", "#94a3b8", "Produto sem estoque na loja.", "Sem preço até voltar."],
  ["TIMEOUT / ERRO", "#94a3b8", "A página demorou demais ou algo inesperado ocorreu.", "O sistema tenta de novo; se falhar, refaça."],
];

const FAQ = [
  [
    "Por que a Magalu bloqueia a coleta automática?",
    "A loja usa uma proteção contra robôs que recusa navegadores controlados por programa, mesmo no seu computador. O SEARCHING registra o bloqueio com o print e segue, sem tentar contornar. Por isso a Magalu usa a Coleta assistida: um clique seu por produto.",
  ],
  [
    "O que a extensão do Chrome faz (e não faz)?",
    "Ela só age quando você aperta Próximo: abre aquele produto numa aba dedicada, tira o print, lê o preço e envia ao SEARCHING no seu próprio computador. Só navega pelas lojas permitidas, espera pelo menos 3 segundos entre páginas, não resolve captcha e não abre links por conta própria.",
  ],
  [
    "Como funciona o alerta de queda?",
    "Depois de cada coleta válida, o preço é comparado ao último (ou ao menor/média dos últimos dias, à sua escolha). Se a queda passa do limite (5% por padrão), sai um e-mail com preço anterior e atual, link e o print. O mesmo preço nunca é avisado duas vezes. As regras ficam em Alertas.",
  ],
  [
    "Onde ficam os meus dados?",
    "Tudo fica neste computador: o banco em backend/data/searching.db e os prints em backend/prints. Nada é enviado para fora, exceto o e-mail de alerta que você configurou. As credenciais de e-mail ficam só no arquivo .env.",
  ],
  [
    "O que é um preço “suspeito”?",
    "É uma leitura que difere muito da última coleta válida (mais de 40%). Quase sempre é erro de leitura ou de página. Ele fica registrado para você conferir, mas não dispara alerta nem entra nas curvas.",
  ],
  [
    "Posso acompanhar outras lojas?",
    "Cada loja precisa de um adaptador (um módulo com os seletores dela). Hoje só a Magazine Luiza tem. O código foi organizado para que uma loja nova não mude o resto do sistema.",
  ],
  [
    "Os preços aparecem como PIX e cartão 1x. Por quê?",
    "São as duas bases que o sistema guarda como números (em centavos), para o cálculo de variação ser exato. O alerta pode usar qualquer uma; o padrão é o PIX.",
  ],
];

const fmtData = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const fmtDuracao = (s) => (s == null ? "" : s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`);
const simplificar = (s) => {
  if (!s) return s;
  const m = String(s).match(/(.{3,}?\b\d{2,4}\s*GB\b)/i);
  return m ? m[1].trim() : String(s).split(",")[0].split(" - ")[0].trim();
};

function proximasAcoes(saude, totalProdutos) {
  const acoes = [];
  if (totalProdutos === 0) acoes.push({ texto: "Nenhum produto cadastrado. Comece adicionando links.", para: "/links", acao: "Cadastrar produtos" });
  if (saude?.links_em_revisao > 0)
    acoes.push({ texto: `${saude.links_em_revisao} link(s) aguardando a sua decisão.`, para: "/review", acao: "Abrir Revisão" });
  const ultima = saude?.ultima_execucao;
  const idadeDias = ultima ? (Date.now() - new Date(ultima.iniciada_em).getTime()) / 86400000 : null;
  if (totalProdutos > 0 && (idadeDias == null || idadeDias > 3))
    acoes.push({ texto: ultima ? `A última coleta foi há ${Math.floor(idadeDias)} dias.` : "Ainda não há nenhuma coleta.", para: "/assisted", acao: "Coletar agora" });
  if (saude?.alertas?.falhos > 0)
    acoes.push({ texto: `${saude.alertas.falhos} alerta(s) de preço não puderam ser enviados por e-mail.`, para: "/alerts", acao: "Conferir e-mail" });
  const comFalha = saude?.produtos_com_falha_na_ultima_coleta?.length || 0;
  if (comFalha > 0) acoes.push({ texto: `${comFalha} produto(s) com erro na última coleta.`, para: "/reports", acao: "Ver relatórios" });
  return acoes;
}

export default function Home() {
  const { pode, modo } = useAuth();
  const [saude, setSaude] = useState(null);
  const [links, setLinks] = useState([]);
  // coleta automática
  const [lojasSel, setLojasSel] = useState([]);
  const [selecionados, setSelecionados] = useState([]);
  const [abrirModelos, setAbrirModelos] = useState(false);
  const [rodando, setRodando] = useState(false);
  const [msg, setMsg] = useState("");

  const carregarSaude = useCallback(() => {
    fetch("/api/saude")
      .then((r) => r.json())
      .then(setSaude)
      .catch(() => setSaude(null));
  }, []);

  useEffect(() => {
    carregarSaude();
    fetch("/api/links")
      .then((r) => r.json())
      .then((j) => {
        const lista = Array.isArray(j) ? j : [];
        setLinks(lista);
        setLojasSel(Array.from(new Set(lista.map((l) => l.LOJA).filter(Boolean))));
      })
      .catch(() => setLinks([]));
  }, [carregarSaude]);

  const lojas = Array.from(new Set(links.map((l) => l.LOJA).filter(Boolean)));
  const modelos = Array.from(new Set(links.map((l) => simplificar(l["NOME COMERCIAL"] || "")).filter(Boolean)));

  const coletar = async () => {
    setRodando(true);
    setMsg("Coletando… o Chrome vai abrir na sua tela. Isso pode levar alguns minutos.");
    try {
      const res = await fetch("/api/coletar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stores: lojasSel, include: selecionados, exclude: [] }),
      });
      const j = await res.json();
      setMsg(j.message || j.error || "Coleta concluída.");
    } catch {
      setMsg("Não consegui falar com o servidor.");
    } finally {
      setRodando(false);
      carregarSaude();
    }
  };

  const acoes = proximasAcoes(saude, links.length);
  const lojaUnica = saude?.lojas?.length === 1 ? saude.lojas[0] : null;
  const ultima = saude?.ultima_execucao;
  const taxaGeral = saude?.lojas?.length ? Math.round((saude.lojas.reduce((a, l) => a + l.ok, 0) / saude.lojas.reduce((a, l) => a + l.total, 0)) * 1000) / 10 : null;

  return (
    <div className="page">
      {/* ===== apresentação ===== */}
      <section className="hero">
        <span className="eyebrow">Monitor de preços com evidência em print</span>
        <h1>SEARCHING</h1>
        <p>
          Acompanha o preço dos seus produtos nas lojas, guarda uma foto da página no momento da coleta como prova e avisa por e-mail quando o
          preço cai. Tudo roda e fica salvo no seu computador.
        </p>
        <div className="row">
          <Link className="btn primary" to="/assisted">
            Começar a coleta assistida
          </Link>
          <Link className="btn secondary" to="/reports">
            Ver relatórios
          </Link>
          <a className="btn ghost" href="#como-funciona">
            Como funciona
          </a>
        </div>
      </section>

      {/* ===== como está agora ===== */}
      <section className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">Como está agora</span>
          <h3>Resumo dos últimos {saude?.periodo_dias || 7} dias</h3>
        </div>
        <div className="metrics">
          <div className="metric">
            <span className="muted">Taxa de sucesso</span>
            <strong>{taxaGeral == null ? "—" : `${String(taxaGeral).replace(".", ",")}%`}</strong>
            <span className="muted">{lojaUnica ? `${lojaUnica.ok} de ${lojaUnica.total} leituras` : saude?.lojas?.length ? `${saude.lojas.length} lojas` : "sem coletas no período"}</span>
          </div>
          <div className="metric">
            <span className="muted">Última coleta</span>
            <strong style={{ fontSize: 20 }}>{ultima ? fmtData(ultima.iniciada_em) : "—"}</strong>
            <span className="muted">
              {ultima
                ? `${ultima.ok} de ${ultima.total} ok · ${ultima.origem}${ultima.em_andamento ? " (em andamento)" : ultima.duracao_s != null ? ` · ${fmtDuracao(ultima.duracao_s)}` : ""}`
                : "nenhuma ainda"}
            </span>
          </div>
          <div className="metric">
            <span className="muted">Links em revisão</span>
            <strong>{saude?.links_em_revisao ?? "—"}</strong>
            <Link to="/review">abrir Revisão</Link>
          </div>
          <div className="metric">
            <span className="muted">Alertas enviados</span>
            <strong>{saude?.alertas?.enviados ?? "—"}</strong>
            <span className="muted">{saude?.alertas?.falhos ? `${saude.alertas.falhos} com falha de envio` : "nenhuma falha"}</span>
          </div>
        </div>

        {saude && Object.keys(saude.falhas_por_status || {}).length > 0 && (
          <p className="note" style={{ margin: 0 }}>
            Falhas no período: {Object.entries(saude.falhas_por_status).map(([s, n]) => `${s.replaceAll("_", " ")} (${n})`).join(", ")}.
          </p>
        )}

        <div className="stack">
          <strong>O que fazer agora</strong>
          {acoes.length === 0 && <span className="note">Tudo em dia. Nada pendente.</span>}
          {acoes.map((a) => (
            <div key={a.texto} className="row" style={{ justifyContent: "space-between" }}>
              <span>{a.texto}</span>
              <Link className="btn secondary" to={a.para}>
                {a.acao}
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* ===== como funciona ===== */}
      <section id="como-funciona" className="stack">
        <div className="card-title">
          <span className="eyebrow">Como funciona</span>
          <h2>Do link ao alerta, em cinco passos</h2>
        </div>
        <div className="steps">
          {PASSOS.map((p, i) => {
            const miolo = (
              <>
                <span className="step-num">{i + 1}</span>
                <div className="step-corpo">
                  <h3>{p.titulo}</h3>
                  <p>{p.texto}</p>
                </div>
                <span className="go">{p.acao} →</span>
              </>
            );
            return p.para.startsWith("#") ? (
              <a key={p.titulo} className="step" href={p.para}>
                {miolo}
              </a>
            ) : (
              <Link key={p.titulo} className="step" to={p.para}>
                {miolo}
              </Link>
            );
          })}
        </div>
      </section>

      {/* ===== coleta automática ===== */}
      <section className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">Coleta automática</span>
          <h3>Para lojas que aceitam robô</h3>
        </div>
        <p className="note" style={{ margin: 0 }}>
          Abre o Chrome sozinho, produto por produto, com pausas entre as páginas. <strong>Está sujeita a bloqueio pela loja:</strong> a Magazine
          Luiza recusa este modo (você verá BLOQUEIO nos resultados; para ela use a Coleta assistida). Depois de dois bloqueios seguidos na mesma
          loja o sistema para de insistir.
        </p>
        <div className="toolbar">
          <span className="muted">Lojas</span>
          {lojas.length === 0 && <span className="muted">Cadastre produtos em Links.</span>}
          {lojas.map((l) => (
            <label key={l} className="chip">
              <input
                type="checkbox"
                checked={lojasSel.includes(l)}
                onChange={(e) => setLojasSel((prev) => (e.target.checked ? [...prev, l] : prev.filter((x) => x !== l)))}
              />
              <span>{l}</span>
            </label>
          ))}
          <button className="btn ghost" onClick={() => setAbrirModelos((v) => !v)}>
            Modelos ({selecionados.length === 0 ? "todos" : selecionados.length}) {abrirModelos ? "▼" : "▶"}
          </button>
        </div>
        {abrirModelos && (
          <div className="card ghost stack">
            <div className="toolbar">
              <button className="btn ghost" onClick={() => setSelecionados(modelos)}>
                Selecionar todos
              </button>
              <button className="btn ghost" onClick={() => setSelecionados([])}>
                Limpar
              </button>
              <span className="muted">Sem nenhum marcado, todos entram.</span>
            </div>
            <div className="option-grid">
              {modelos.map((m) => (
                <label key={m} className="row" style={{ justifyContent: "flex-start" }}>
                  <input
                    type="checkbox"
                    checked={selecionados.includes(m)}
                    onChange={(e) => setSelecionados((prev) => (e.target.checked ? [...prev, m] : prev.filter((x) => x !== m)))}
                  />
                  <span>{m}</span>
                </label>
              ))}
            </div>
          </div>
        )}
        <div className="toolbar">
          <button className="btn primary" onClick={coletar} disabled={rodando || lojasSel.length === 0 || modo === "hospedado" || !pode("admin")}
            title={modo === "hospedado" ? "No modo hospedado a coleta é feita pela extensão (Coleta assistida)." : undefined}>
            {rodando ? "Coletando…" : "Iniciar coleta automática"}
          </button>
        </div>
        {msg && <p className="status" style={{ margin: 0 }}>{msg}</p>}
      </section>

      {/* ===== glossário de status ===== */}
      <section id="status" className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">Glossário</span>
          <h3>O que cada status significa</h3>
        </div>
        <div className="status-grid">
          {STATUS.map(([nome, cor, o_que, fazer]) => (
            <div key={nome} className="status-item">
              <span className="status-pill" style={{ color: cor }}>
                {nome}
              </span>
              <span style={{ fontSize: 14 }}>
                {o_que} <span className="muted">{fazer}</span>
              </span>
            </div>
          ))}
        </div>
        <p className="note" style={{ margin: 0 }}>
          Nunca existe <strong>OK</strong> sem um preço válido, e só coletas OK entram nas curvas e podem gerar alerta.
        </p>
      </section>

      {/* ===== perguntas frequentes ===== */}
      <section className="card wide stack faq">
        <div className="card-title">
          <span className="eyebrow">Perguntas frequentes</span>
          <h3>Dúvidas comuns</h3>
        </div>
        {FAQ.map(([pergunta, resposta]) => (
          <details key={pergunta}>
            <summary>{pergunta}</summary>
            <p>{resposta}</p>
          </details>
        ))}
      </section>

      {/* ===== atalhos ===== */}
      <section className="card wide stack">
        <div className="card-title">
          <span className="eyebrow">Atalhos</span>
          <h3>Na Coleta assistida</h3>
        </div>
        <div className="row" style={{ gap: 20 }}>
          <span>
            <span className="kbd">Espaço</span> ou <span className="kbd">→</span> abre o próximo produto
          </span>
          <span className="muted">Refazer, Pular e Link quebrado ficam ao lado do botão Próximo. Erros aparecem num aviso amarelo no topo.</span>
        </div>
      </section>
    </div>
  );
}
