import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

// ---------- fetch com CSRF ----------
// No modo hospedado toda escrita leva o token CSRF da sessão. Os componentes continuam usando fetch("/api/...").
let csrfAtual = null;
const fetchOriginal = window.fetch.bind(window);
window.fetch = (entrada, init = {}) => {
  const url = typeof entrada === "string" ? entrada : entrada.url;
  const metodo = (init.method || (typeof entrada !== "string" && entrada.method) || "GET").toUpperCase();
  if (csrfAtual && url.startsWith("/api/") && !["GET", "HEAD", "OPTIONS"].includes(metodo)) {
    init = { ...init, headers: { ...(init.headers || {}), "X-CSRF-Token": csrfAtual } };
  }
  return fetchOriginal(entrada, init).then((res) => {
    if (res.status === 401 && url.startsWith("/api/") && !url.startsWith("/api/auth/")) {
      window.dispatchEvent(new Event("sessao-expirada"));
    }
    return res;
  });
};

const NIVEL = { leitor: 0, coletor: 1, admin: 2 };
const AuthContext = createContext({ usuario: null, modo: "local", pode: () => true, atribuidos: null });
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [estado, setEstado] = useState({ carregando: true, usuario: null, modo: "local", atribuidos: null, precisa2fa: false, erro: "" });

  const carregar = useCallback(async () => {
    try {
      const res = await fetch("/api/auth/eu");
      if (res.status === 401) {
        csrfAtual = null;
        return setEstado({ carregando: false, usuario: null, modo: "hospedado", atribuidos: null, erro: "" });
      }
      const j = await res.json();
      csrfAtual = j.csrf || null;
      setEstado({ carregando: false, usuario: j.usuario, modo: j.modo, atribuidos: j.atribuidos, precisa2fa: !!j.precisa_2fa, erro: "" });
    } catch {
      setEstado((e) => ({ ...e, carregando: false, erro: "Não consegui falar com o servidor." }));
    }
  }, []);

  useEffect(() => {
    carregar();
    const expirou = () => setEstado((e) => (e.modo === "hospedado" ? { ...e, usuario: null } : e));
    window.addEventListener("sessao-expirada", expirou);
    return () => window.removeEventListener("sessao-expirada", expirou);
  }, [carregar]);

  const sair = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    csrfAtual = null;
    setEstado((e) => ({ ...e, usuario: null }));
  };

  const pode = (papel) => !!estado.usuario && NIVEL[estado.usuario.papel] >= NIVEL[papel];
  return <AuthContext.Provider value={{ ...estado, pode, recarregar: carregar, sair }}>{children}</AuthContext.Provider>;
}

// ---------- telas ----------
async function chamar(url, metodo, corpo) {
  const res = await fetch(url, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const json = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, json };
}

export function Login() {
  const { recarregar } = useAuth();
  const [form, setForm] = useState({ email: "", senha: "", codigo: "" });
  const [precisaCodigo, setPrecisaCodigo] = useState(false);
  const [msg, setMsg] = useState("");
  const [modoTela, setModoTela] = useState("entrar"); // entrar | recuperar | redefinir
  const token = new URLSearchParams(window.location.search).get("token");

  useEffect(() => {
    if (window.location.pathname === "/redefinir" && token) setModoTela("redefinir");
  }, [token]);

  const entrar = async (e) => {
    e.preventDefault();
    const r = await chamar("/api/auth/login", "POST", form);
    if (r.ok) return recarregar();
    if (r.json.codigo === "2fa_necessario") setPrecisaCodigo(true);
    setMsg(r.json.error || "Não foi possível entrar.");
  };
  const recuperar = async (e) => {
    e.preventDefault();
    const r = await chamar("/api/auth/recuperar", "POST", { email: form.email });
    setMsg(r.json.message || r.json.error);
  };
  const redefinir = async (e) => {
    e.preventDefault();
    const r = await chamar("/api/auth/redefinir", "POST", { token, senha: form.senha });
    setMsg(r.json.message || r.json.error);
    if (r.ok) {
      window.history.replaceState({}, "", "/");
      setModoTela("entrar");
    }
  };

  const campo = (rotulo, chave, tipo = "text") => (
    <label className="stack">
      <span className="note">{rotulo}</span>
      <input className="input" type={tipo} value={form[chave]} onChange={(e) => setForm({ ...form, [chave]: e.target.value })} />
    </label>
  );

  return (
    <div className="page" style={{ maxWidth: 420, margin: "10vh auto" }}>
      <div className="card wide stack">
        <h2 className="logo">SEARCHING</h2>
        {modoTela === "entrar" && (
          <form className="stack" onSubmit={entrar}>
            {campo("E-mail", "email", "email")}
            {campo("Senha", "senha", "password")}
            {precisaCodigo && campo("Código do autenticador", "codigo")}
            <button className="btn primary" type="submit">Entrar</button>
            <button className="btn ghost" type="button" onClick={() => { setModoTela("recuperar"); setMsg(""); }}>Esqueci a senha</button>
          </form>
        )}
        {modoTela === "recuperar" && (
          <form className="stack" onSubmit={recuperar}>
            {campo("E-mail da conta", "email", "email")}
            <button className="btn primary" type="submit">Enviar link</button>
            <button className="btn ghost" type="button" onClick={() => { setModoTela("entrar"); setMsg(""); }}>Voltar</button>
          </form>
        )}
        {modoTela === "redefinir" && (
          <form className="stack" onSubmit={redefinir}>
            {campo("Nova senha (mínimo 12 caracteres)", "senha", "password")}
            <button className="btn primary" type="submit">Salvar nova senha</button>
          </form>
        )}
        {msg && <p className="status">{msg}</p>}
      </div>
    </div>
  );
}

export function Conta() {
  const { usuario, modo, recarregar, precisa2fa } = useAuth();
  const [sessoes, setSessoes] = useState([]);
  const [senha, setSenha] = useState({ atual: "", nova: "" });
  const [msg, setMsg] = useState("");
  const [tokens, setTokens] = useState([]);
  const [novoToken, setNovoToken] = useState(null);
  const [doisFatores, setDoisFatores] = useState(null);
  const [codigo, setCodigo] = useState("");

  const carregarTokens = useCallback(async () => {
    const r = await chamar("/api/meus-tokens", "GET");
    if (r.ok) setTokens(r.json);
  }, []);
  const carregarSessoes = useCallback(async () => {
    const r = await chamar("/api/minhas-sessoes", "GET");
    if (r.ok) setSessoes(r.json);
  }, []);
  useEffect(() => { if (modo === "hospedado") { carregarTokens(); carregarSessoes(); } }, [modo, carregarTokens, carregarSessoes]);
  const encerrarSessao = async (id) => { await chamar(`/api/minhas-sessoes/${id}`, "DELETE"); carregarSessoes(); };
  const encerrarOutras = async () => { await chamar("/api/minhas-sessoes/encerrar-outras", "POST", {}); carregarSessoes(); };

  if (modo !== "hospedado") return <div className="page"><div className="card wide"><p>No modo local não há contas: tudo roda neste computador.</p></div></div>;

  const trocar = async (e) => {
    e.preventDefault();
    const r = await chamar("/api/auth/trocar-senha", "POST", senha);
    setMsg(r.json.message || r.json.error);
    if (r.ok) { setSenha({ atual: "", nova: "" }); recarregar(); }
  };
  const criarToken = async (tipo) => {
    const r = await chamar("/api/meus-tokens", "POST", { tipo, nome: tipo === "leitura" ? "Planilha/BI" : "Extensão (manual)" });
    if (r.ok) { setNovoToken(r.json); carregarTokens(); } else setMsg(r.json.error);
  };
  const revogar = async (id) => { await chamar(`/api/meus-tokens/${id}`, "DELETE"); carregarTokens(); };
  const iniciar2fa = async () => { const r = await chamar("/api/auth/2fa/iniciar", "POST", {}); r.ok ? setDoisFatores(r.json) : setMsg(r.json.error); };
  const ativar2fa = async () => {
    const r = await chamar("/api/auth/2fa/ativar", "POST", { codigo });
    setMsg(r.json.message || r.json.error);
    if (r.ok) { setDoisFatores(null); recarregar(); }
  };

  return (
    <div className="page">
      {precisa2fa && (
        <div className="card wide" role="alert">
          <p className="status">Administradores precisam ativar a verificação em duas etapas antes de usar o sistema. Faça isso abaixo.</p>
        </div>
      )}
      <div className="card wide stack">
        <h3>{usuario.nome || usuario.email} <span className="chip">{usuario.papel}</span></h3>
        <form className="stack" onSubmit={trocar}>
          <label className="stack"><span className="note">Senha atual</span>
            <input className="input" type="password" value={senha.atual} onChange={(e) => setSenha({ ...senha, atual: e.target.value })} /></label>
          <label className="stack"><span className="note">Nova senha (mínimo 12 caracteres)</span>
            <input className="input" type="password" value={senha.nova} onChange={(e) => setSenha({ ...senha, nova: e.target.value })} /></label>
          <button className="btn primary" type="submit">Trocar senha</button>
        </form>
        {msg && <p className="status">{msg}</p>}
      </div>

      <div className="card wide stack">
        <h3>Verificação em duas etapas</h3>
        {usuario.totp_ativo ? <p className="note">Ativa.</p> : doisFatores ? (
          <div className="stack">
            <p className="note">Adicione ao aplicativo autenticador a chave: <code>{doisFatores.segredo}</code></p>
            <input className="input" placeholder="Código de 6 dígitos" value={codigo} onChange={(e) => setCodigo(e.target.value)} />
            <button className="btn primary" onClick={ativar2fa}>Ativar</button>
          </div>
        ) : <button className="btn secondary" onClick={iniciar2fa}>Ativar verificação em duas etapas</button>}
      </div>

      <div className="card wide stack">
        <h3>Sessões ativas</h3>
        {sessoes.map((x) => (
          <div className="row" key={x.id}>
            <span className="note">
              {x.atual ? "Esta sessão · " : ""}entrou em {x.criada_em} · último uso {x.ultimo_uso} · IP {x.ip || "—"} · {x.navegador || "navegador desconhecido"}
            </span>
            <button className="btn ghost" onClick={() => encerrarSessao(x.id)}>{x.atual ? "Sair desta" : "Encerrar"}</button>
          </div>
        ))}
        {sessoes.length > 1 && <button className="btn secondary" onClick={encerrarOutras}>Encerrar todas as outras</button>}
      </div>

      <div className="card wide stack">
        <h3>Tokens</h3>
        <p className="note">O token da extensão é criado automaticamente na tela Coleta assistida. Aqui você cria um token somente leitura para planilhas/BI.</p>
        <div className="toolbar">
          <button className="btn secondary" onClick={() => criarToken("leitura")}>Criar token de leitura</button>
          {usuario.papel !== "leitor" && <button className="btn secondary" onClick={() => criarToken("extensao")}>Criar token da extensão (colar nas opções)</button>}
        </div>
        {novoToken && <p className="status">{novoToken.aviso} <code>{novoToken.token}</code></p>}
        {tokens.map((t) => (
          <div className="row" key={t.id}>
            <span>{t.tipo} · {t.nome} · {t.prefixo}… {t.revogado ? "(revogado)" : ""}</span>
            {!t.revogado && <button className="btn ghost" onClick={() => revogar(t.id)}>Revogar</button>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Usuarios() {
  const [lista, setLista] = useState([]);
  const [novo, setNovo] = useState({ email: "", nome: "", papel: "leitor" });
  const [msg, setMsg] = useState("");
  const [produtos, setProdutos] = useState([]);
  const [atrib, setAtrib] = useState({});
  const [tokens, setTokens] = useState({});
  const [auditoria, setAuditoria] = useState([]);
  const [sessoes, setSessoes] = useState([]);
  const [retencao, setRetencao] = useState(0);
  const [msgRetencao, setMsgRetencao] = useState("");

  const carregar = useCallback(async () => {
    const [u, p, a, au, se, re] = await Promise.all([
      chamar("/api/usuarios", "GET"), chamar("/api/links", "GET"), chamar("/api/atribuicoes", "GET"), chamar("/api/auditoria?limite=50", "GET"),
      chamar("/api/sessoes", "GET"), chamar("/api/retencao", "GET"),
    ]);
    if (se.ok) setSessoes(se.json);
    if (re.ok) setRetencao(re.json.dias);
    if (u.ok) setLista(u.json);
    if (p.ok) setProdutos(p.json);
    if (a.ok) setAtrib(a.json);
    if (au.ok) setAuditoria(au.json);
  }, []);
  useEffect(() => { carregar(); }, [carregar]);

  const criar = async (e) => {
    e.preventDefault();
    const r = await chamar("/api/usuarios", "POST", novo);
    setMsg(r.ok ? `${r.json.aviso} Senha provisória de ${r.json.usuario.email}: ${r.json.senha_temporaria}` : r.json.error);
    if (r.ok) { setNovo({ email: "", nome: "", papel: "leitor" }); carregar(); }
  };
  const alterar = async (id, corpo) => { const r = await chamar(`/api/usuarios/${id}`, "PATCH", corpo); if (!r.ok) setMsg(r.json.error); carregar(); };
  const redefinir = async (id) => { const r = await chamar(`/api/usuarios/${id}/redefinir-senha`, "POST", {}); setMsg(r.ok ? `Senha provisória: ${r.json.senha_temporaria}` : r.json.error); };
  const verTokens = async (id) => { const r = await chamar(`/api/usuarios/${id}/tokens`, "GET"); if (r.ok) setTokens({ ...tokens, [id]: r.json }); };
  const revogar = async (uid, tid) => { await chamar(`/api/tokens/${tid}`, "DELETE"); verTokens(uid); };
  const encerrarSessaoDe = async (id) => { await chamar(`/api/sessoes/${id}`, "DELETE"); carregar(); };
  const salvarRetencao = async () => {
    const r = await chamar("/api/retencao", "PUT", { dias: Number(retencao) });
    setMsgRetencao(r.ok ? "Salvo." : r.json.error);
  };
  const aplicarRetencao = async (simular) => {
    const r = await chamar("/api/retencao/aplicar", "POST", { simular });
    setMsgRetencao(r.ok ? `${simular ? "Simulação: " : ""}${r.json.removidos} removido(s), ${r.json.arquivados} arquivado(s).` : r.json.error);
  };
  const alternarProduto = async (uid, pid) => {
    const atuais = new Set(atrib[uid] || []);
    atuais.has(pid) ? atuais.delete(pid) : atuais.add(pid);
    const r = await chamar(`/api/atribuicoes/${uid}`, "PUT", { produtos: [...atuais] });
    if (r.ok) setAtrib({ ...atrib, [uid]: r.json.produtos });
  };

  return (
    <div className="page">
      <div className="card wide stack">
        <h3>Novo usuário</h3>
        <form className="grid-2" onSubmit={criar}>
          <input className="input" placeholder="E-mail" value={novo.email} onChange={(e) => setNovo({ ...novo, email: e.target.value })} />
          <input className="input" placeholder="Nome" value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} />
          <select className="input" value={novo.papel} onChange={(e) => setNovo({ ...novo, papel: e.target.value })}>
            <option value="leitor">leitor (só vê)</option><option value="coletor">coletor</option><option value="admin">admin</option>
          </select>
          <button className="btn primary" type="submit">Criar</button>
        </form>
        {msg && <p className="status">{msg}</p>}
      </div>

      {lista.map((u) => (
        <div className="card wide stack" key={u.id}>
          <div className="row">
            <strong>{u.nome || u.email}</strong> <span className="note">{u.email}</span>
            <select className="input" value={u.papel} onChange={(e) => alterar(u.id, { papel: e.target.value })}>
              <option value="leitor">leitor</option><option value="coletor">coletor</option><option value="admin">admin</option>
            </select>
            <button className="btn ghost" onClick={() => alterar(u.id, { ativo: !u.ativo })}>{u.ativo ? "Desativar" : "Reativar"}</button>
            <button className="btn ghost" onClick={() => redefinir(u.id)}>Redefinir senha</button>
            <button className="btn ghost" onClick={() => verTokens(u.id)}>Tokens</button>
          </div>
          {(tokens[u.id] || []).map((t) => (
            <div className="row" key={t.id}>
              <span className="note">{t.tipo} · {t.nome} · {t.prefixo}… · último uso {t.ultimo_uso || "nunca"} {t.revogado ? "(revogado)" : ""}</span>
              {!t.revogado && <button className="btn ghost" onClick={() => revogar(u.id, t.id)}>Revogar</button>}
            </div>
          ))}
          {u.papel === "coletor" && (
            <details>
              <summary className="note">Produtos atribuídos ({(atrib[u.id] || []).length})</summary>
              {produtos.map((p) => (
                <label className="row" key={p.ID}>
                  <input type="checkbox" checked={(atrib[u.id] || []).includes(p.ID)} onChange={() => alternarProduto(u.id, p.ID)} />
                  <span>{p["NOME COMERCIAL"]} <span className="note">({p.LOJA})</span></span>
                </label>
              ))}
            </details>
          )}
        </div>
      ))}

      <div className="card wide stack">
        <h3>Retenção dos prints</h3>
        <p className="note">Prints podem mostrar nome e CEP de quem coletou. Apague os antigos depois de N dias (0 = guardar para sempre). O histórico de preços continua.</p>
        <div className="row">
          <label className="row"><span className="note">Dias</span>
            <input className="input" type="number" min="0" max="3650" style={{ width: 100 }} value={retencao} onChange={(e) => setRetencao(e.target.value)} /></label>
          <button className="btn secondary" onClick={salvarRetencao}>Salvar</button>
          <button className="btn ghost" onClick={() => aplicarRetencao(true)}>Simular</button>
          <button className="btn ghost" onClick={() => window.confirm("Apagar agora os prints mais antigos que o prazo?") && aplicarRetencao(false)}>Aplicar agora</button>
        </div>
        {msgRetencao && <p className="status">{msgRetencao}</p>}
      </div>

      <div className="card wide stack">
        <h3>Sessões ativas de todos</h3>
        {sessoes.map((x) => (
          <div className="row" key={x.id}>
            <span className="note">{x.usuario} · último uso {x.ultimo_uso} · IP {x.ip || "—"}{x.atual ? " · (a sua)" : ""}</span>
            {!x.atual && <button className="btn ghost" onClick={() => encerrarSessaoDe(x.id)}>Encerrar</button>}
          </div>
        ))}
      </div>

      <div className="card wide stack">
        <h3>Auditoria (últimos 50 eventos)</h3>
        {auditoria.map((a) => (
          <p className="note" key={a.id}>{a.em} · {a.usuario || "—"} · {a.acao} {a.alvo}</p>
        ))}
      </div>
    </div>
  );
}
