import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { api, chamadas } from "./mock-api.js";
import { AuthProvider, Conta, Login, Usuarios, useAuth } from "../auth.jsx";

const USUARIO = { id: 2, email: "coletor@x.com", nome: "Coletor", papel: "coletor", totp_ativo: false, ativo: true };

function Porta() {
  const { carregando, usuario } = useAuth();
  if (carregando) return <p>carregando</p>;
  return usuario ? <p>Logado como {usuario.email}</p> : <Login />;
}

const tela = (filho = <Porta />) => render(<AuthProvider>{filho}</AuthProvider>);
const ultima = (metodo, url) => [...chamadas].reverse().find((c) => c.metodo === metodo && c.url.startsWith(url));

describe("Login", () => {
  it("entra com e-mail e senha e passa a mostrar o usuário", async () => {
    let logado = false;
    api({
      "GET /api/auth/eu": () => (logado ? { modo: "hospedado", usuario: USUARIO, csrf: "tok", atribuidos: [] } : [401, { error: "Entre" }]),
      "POST /api/auth/login": () => { logado = true; return { usuario: USUARIO, csrf: "tok" }; },
    });
    const u = userEvent.setup();
    tela();
    await u.type(await screen.findByLabelText("E-mail"), "coletor@x.com");
    await u.type(screen.getByLabelText("Senha"), "Senha-Forte-123");
    await u.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("Logado como coletor@x.com")).toBeInTheDocument();
    expect(ultima("POST", "/api/auth/login").corpo).toMatchObject({ email: "coletor@x.com", senha: "Senha-Forte-123" });
  });

  it("mostra o erro do servidor e continua na tela de login", async () => {
    api({
      "GET /api/auth/eu": [401, { error: "Entre" }],
      "POST /api/auth/login": [401, { error: "E-mail ou senha incorretos.", codigo: "credenciais" }],
    });
    const u = userEvent.setup();
    tela();
    await u.type(await screen.findByLabelText("E-mail"), "x@x.com");
    await u.type(screen.getByLabelText("Senha"), "errada");
    await u.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("E-mail ou senha incorretos.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Entrar" })).toBeInTheDocument();
  });

  it("pede o código do autenticador quando a conta tem 2FA e o envia junto", async () => {
    api({
      "GET /api/auth/eu": [401, { error: "Entre" }],
      "POST /api/auth/login": (_, { corpo }) =>
        corpo.codigo ? { usuario: USUARIO, csrf: "t" } : [401, { error: "Informe o código do aplicativo autenticador.", codigo: "2fa_necessario" }],
    });
    const u = userEvent.setup();
    tela();
    await u.type(await screen.findByLabelText("E-mail"), "x@x.com");
    await u.type(screen.getByLabelText("Senha"), "Senha-Forte-123");
    await u.click(screen.getByRole("button", { name: "Entrar" }));
    const campo = await screen.findByLabelText("Código do autenticador");
    await u.type(campo, "123456");
    await u.click(screen.getByRole("button", { name: "Entrar" }));
    await waitFor(() => expect(ultima("POST", "/api/auth/login").corpo.codigo).toBe("123456"));
  });

  it("recuperação de senha mostra a mesma mensagem genérica do servidor", async () => {
    api({
      "GET /api/auth/eu": [401, { error: "Entre" }],
      "POST /api/auth/recuperar": { message: "Se este e-mail tem conta, enviamos um link para redefinir a senha." },
    });
    const u = userEvent.setup();
    tela();
    await u.click(await screen.findByRole("button", { name: "Esqueci a senha" }));
    await u.type(screen.getByLabelText("E-mail da conta"), "alguem@x.com");
    await u.click(screen.getByRole("button", { name: "Enviar link" }));
    expect(await screen.findByText(/Se este e-mail tem conta/)).toBeInTheDocument();
  });

  it("depois do login, as escritas levam o token CSRF da sessão", async () => {
    api({
      "GET /api/auth/eu": { modo: "hospedado", usuario: USUARIO, csrf: "csrf-da-sessao", atribuidos: [] },
      "POST /api/qualquer": { ok: true },
    });
    function Escreve() {
      const { usuario } = useAuth();
      return usuario ? <button onClick={() => fetch("/api/qualquer", { method: "POST", body: "{}" })}>enviar</button> : null;
    }
    const u = userEvent.setup();
    tela(<Escreve />);
    await u.click(await screen.findByRole("button", { name: "enviar" }));
    await waitFor(() => expect(ultima("POST", "/api/qualquer").headers["X-CSRF-Token"]).toBe("csrf-da-sessao"));
  });
});

describe("Minha conta", () => {
  const eu = (extra = {}) => ({ modo: "hospedado", usuario: USUARIO, csrf: "t", atribuidos: [], ...extra });

  it("lista as sessões, marca a atual e encerra uma outra", async () => {
    const sessoes = [
      { id: 1, atual: true, criada_em: "2026-10-25T10:00:00", ultimo_uso: "2026-10-25T10:05:00", ip: "1.1.1.1", navegador: "Chrome" },
      { id: 2, atual: false, criada_em: "2026-10-24T10:00:00", ultimo_uso: "2026-10-24T11:00:00", ip: "2.2.2.2", navegador: "Edge" },
    ];
    api({
      "GET /api/auth/eu": eu(),
      "GET /api/minhas-sessoes": sessoes,
      "GET /api/meus-tokens": [],
      "DELETE /api/minhas-sessoes/2": { message: "Sessão encerrada." },
    });
    const u = userEvent.setup();
    tela(<Conta />);
    expect(await screen.findByText(/Esta sessão/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sair desta/ })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Encerrar a sessão de Edge/ }));
    await waitFor(() => expect(ultima("DELETE", "/api/minhas-sessoes/2")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Encerrar todas as outras" })).toBeInTheDocument();
  });

  it("avisa o administrador que o 2FA é obrigatório", async () => {
    api({
      "GET /api/auth/eu": eu({ usuario: { ...USUARIO, papel: "admin" }, precisa_2fa: true }),
      "GET /api/minhas-sessoes": [],
      "GET /api/meus-tokens": [],
    });
    tela(<Conta />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/verificação em duas etapas/);
  });

  it("mostra o token criado uma vez e a lista de tokens", async () => {
    api({
      "GET /api/auth/eu": eu(),
      "GET /api/minhas-sessoes": [],
      "GET /api/meus-tokens": [{ id: 9, tipo: "leitura", nome: "Planilha/BI", prefixo: "sch_l_abcd", revogado: false }],
      "POST /api/meus-tokens": { token: "sch_l_SEGREDO", aviso: "Guarde agora.", info: {} },
    });
    const u = userEvent.setup();
    tela(<Conta />);
    await u.click(await screen.findByRole("button", { name: "Criar token de leitura" }));
    expect(await screen.findByText("sch_l_SEGREDO")).toBeInTheDocument();
    expect(ultima("POST", "/api/meus-tokens").corpo.tipo).toBe("leitura");
  });

  it("troca de senha envia a senha atual e a nova", async () => {
    api({
      "GET /api/auth/eu": eu(),
      "GET /api/minhas-sessoes": [],
      "GET /api/meus-tokens": [],
      "POST /api/auth/trocar-senha": { message: "Senha alterada." },
    });
    const u = userEvent.setup();
    tela(<Conta />);
    await u.type(await screen.findByLabelText("Senha atual"), "antiga-senha-123");
    await u.type(screen.getByLabelText(/Nova senha/), "nova-senha-forte-9");
    await u.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(await screen.findByText("Senha alterada.")).toBeInTheDocument();
    expect(ultima("POST", "/api/auth/trocar-senha").corpo).toEqual({ atual: "antiga-senha-123", nova: "nova-senha-forte-9" });
  });
});

describe("Usuários (admin)", () => {
  const admin = { modo: "hospedado", usuario: { ...USUARIO, id: 1, email: "admin@x.com", papel: "admin" }, csrf: "t", atribuidos: [] };
  const base = () => ({
    "GET /api/auth/eu": admin,
    "GET /api/usuarios": [
      { id: 1, email: "admin@x.com", nome: "Admin", papel: "admin", ativo: true },
      { id: 2, email: "ana@x.com", nome: "Ana", papel: "coletor", ativo: true },
    ],
    "GET /api/links": [{ ID: 7, "NOME COMERCIAL": "Galaxy S25", LINK: "u", LOJA: "Magazine Luiza" }],
    "GET /api/atribuicoes": { 2: [] },
    "GET /api/auditoria": [{ id: 1, em: "2026-10-25T09:00:00", usuario: "admin@x.com", acao: "login_ok", alvo: "" }],
    "GET /api/sessoes": [{ id: 5, usuario: "ana@x.com", ultimo_uso: "2026-10-25T09:30:00", ip: "3.3.3.3", atual: false }],
    "GET /api/retencao": { dias: 30 },
  });

  it("lista usuários, sessões ativas e auditoria", async () => {
    api(base());
    tela(<Usuarios />);
    expect(await screen.findByText("Ana")).toBeInTheDocument();
    expect(screen.getByText(/ana@x.com · último uso/)).toBeInTheDocument();
    expect(screen.getByText(/login_ok/)).toBeInTheDocument();
    expect(screen.getByLabelText("Dias")).toHaveValue(30);
  });

  it("cria um usuário e mostra a senha provisória uma vez", async () => {
    api({
      ...base(),
      "POST /api/usuarios": [201, { usuario: { email: "novo@x.com" }, senha_temporaria: "Provisoria-123", aviso: "Entregue por um canal seguro." }],
    });
    const u = userEvent.setup();
    tela(<Usuarios />);
    await u.type(await screen.findByPlaceholderText("E-mail"), "novo@x.com");
    await u.selectOptions(screen.getAllByRole("combobox")[0], "coletor");
    await u.click(screen.getByRole("button", { name: "Criar" }));
    expect(await screen.findByText(/Senha provisória de novo@x.com: Provisoria-123/)).toBeInTheDocument();
    expect(ultima("POST", "/api/usuarios").corpo).toMatchObject({ email: "novo@x.com", papel: "coletor" });
  });

  it("muda o papel e desativa um usuário", async () => {
    api({ ...base(), "PATCH /api/usuarios/2": { id: 2 } });
    const u = userEvent.setup();
    tela(<Usuarios />);
    const cartao = (await screen.findByText("Ana")).closest(".card");
    await u.selectOptions(within(cartao).getByRole("combobox", { name: "Papel de Ana" }), "leitor");
    await waitFor(() => expect(ultima("PATCH", "/api/usuarios/2").corpo).toEqual({ papel: "leitor" }));
    await u.click(within(cartao).getByRole("button", { name: "Desativar Ana" }));
    await waitFor(() => expect(ultima("PATCH", "/api/usuarios/2").corpo).toEqual({ ativo: false }));
  });

  it("atribui um produto ao coletor", async () => {
    api({ ...base(), "PUT /api/atribuicoes/2": { produtos: [7] } });
    const u = userEvent.setup();
    tela(<Usuarios />);
    await u.click(await screen.findByText(/Produtos atribuídos/));
    await u.click(screen.getByRole("checkbox", { name: /Galaxy S25/ }));
    await waitFor(() => expect(ultima("PUT", "/api/atribuicoes/2").corpo).toEqual({ produtos: [7] }));
  });

  it("salva e simula a retenção dos prints", async () => {
    api({ ...base(), "PUT /api/retencao": { dias: 45 }, "POST /api/retencao/aplicar": { removidos: 3, arquivados: 0, simulacao: true } });
    const u = userEvent.setup();
    tela(<Usuarios />);
    const campo = await screen.findByLabelText("Dias");
    await u.clear(campo);
    await u.type(campo, "45");
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText("Salvo.")).toBeInTheDocument();
    expect(ultima("PUT", "/api/retencao").corpo).toEqual({ dias: 45 });
    await u.click(screen.getByRole("button", { name: "Simular" }));
    expect(await screen.findByText(/Simulação: 3 removido/)).toBeInTheDocument();
  });

  it("encerra a sessão de outra pessoa", async () => {
    api({ ...base(), "DELETE /api/sessoes/5": { message: "ok" } });
    const u = userEvent.setup();
    tela(<Usuarios />);
    const linha = (await screen.findByText(/ana@x.com · último uso/)).closest(".row");
    await u.click(within(linha).getByRole("button", { name: /Encerrar a sessão de ana@x.com/ }));
    await waitFor(() => expect(ultima("DELETE", "/api/sessoes/5")).toBeTruthy());
  });
});


describe("Acessibilidade das telas novas", () => {
  it("login: campos com nome, autocomplete correto e erro anunciado", async () => {
    api({ "GET /api/auth/eu": [401, { error: "Entre" }], "POST /api/auth/login": [401, { error: "E-mail ou senha incorretos." }] });
    const u = userEvent.setup();
    tela();
    const email = await screen.findByLabelText("E-mail");
    expect(email).toHaveAttribute("autocomplete", "username");
    expect(email).toBeRequired();
    expect(screen.getByLabelText("Senha")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("form", { name: "Entrar" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "SEARCHING" })).toBeInTheDocument();
    await u.type(email, "x@x.com");
    await u.type(screen.getByLabelText("Senha"), "errada");
    await u.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha incorretos.");
  });

  it("usuários: todo campo e botão repetido tem nome próprio (leitor de tela)", async () => {
    api({
      "GET /api/auth/eu": { modo: "hospedado", usuario: { ...USUARIO, id: 1, papel: "admin" }, csrf: "t", atribuidos: [] },
      "GET /api/usuarios": [{ id: 2, email: "ana@x.com", nome: "Ana", papel: "coletor", ativo: true }],
      "GET /api/links": [], "GET /api/atribuicoes": {}, "GET /api/auditoria": [], "GET /api/sessoes": [], "GET /api/retencao": { dias: 0 },
    });
    tela(<Usuarios />);
    expect(await screen.findByRole("textbox", { name: "E-mail do novo usuário" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Nome do novo usuário" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Papel do novo usuário" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Papel de Ana" })).toBeInTheDocument();
    for (const nome of ["Desativar Ana", "Redefinir a senha de Ana", "Ver os tokens de Ana"]) {
      expect(screen.getByRole("button", { name: nome })).toBeInTheDocument();
    }
  });

  it("minha conta: senha nova com autocomplete new-password e mínimo de 12 caracteres", async () => {
    api({ "GET /api/auth/eu": { modo: "hospedado", usuario: USUARIO, csrf: "t", atribuidos: [] }, "GET /api/minhas-sessoes": [], "GET /api/meus-tokens": [] });
    tela(<Conta />);
    const nova = await screen.findByLabelText(/Nova senha/);
    expect(nova).toHaveAttribute("autocomplete", "new-password");
    expect(nova).toHaveAttribute("minlength", "12");
    expect(screen.getByLabelText("Senha atual")).toHaveAttribute("autocomplete", "current-password");
  });
});
