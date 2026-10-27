import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, chamadas } from "./mock-api.js";
import { AuthProvider, useAuth } from "../auth.jsx";
import Assisted from "../pages/Assisted.jsx";

const COLETOR = { id: 2, email: "c@x.com", nome: "Coletor", papel: "coletor", totp_ativo: false, ativo: true };
const hospedado = { modo: "hospedado", usuario: COLETOR, csrf: "t", atribuidos: [] };
const local = { modo: "local", usuario: { ...COLETOR, papel: "admin", email: "local" }, csrf: null, atribuidos: null };

const ultima = (metodo, url) => [...chamadas].reverse().find((c) => c.metodo === metodo && c.url.startsWith(url));

/** Extensão de mentira: responde às mensagens que a página manda pela ponte (window.postMessage). */
function extensaoFalsa({ pareado = false, configurar = { ok: true }, servidor = "https://servidor.exemplo" } = {}) {
  const mensagens = [];
  const responder = (m, resposta) =>
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { origem: "searching-ext", tipo: "resposta", id: m.id, tipoOriginal: m.tipo, ...resposta },
        origin: window.location.origin,
        source: window,
      })
    );
  vi.spyOn(window, "postMessage").mockImplementation((m) => {
    if (!m || m.origem !== "searching-app") return;
    mensagens.push(m);
    if (m.tipo === "ping") responder(m, { ok: true, versao: "2.0.0", pareado, servidor });
    else if (m.tipo === "configurar") responder(m, configurar);
    else if (m.tipo === "navegar") responder(m, { ok: true });
  });
  return mensagens;
}

// como no App de verdade, a página só aparece depois que a sessão (e o modo local/hospedado) foi carregada
function SoDepoisDoLogin({ children }) {
  const { carregando } = useAuth();
  return carregando ? null : children;
}
const tela = () => render(<AuthProvider><SoDepoisDoLogin><Assisted /></SoDepoisDoLogin></AuthProvider>);

afterEach(() => vi.restoreAllMocks());

describe("Coleta assistida: pareamento com a extensão", () => {
  it("modo hospedado, extensão sem pareamento: cria o token do usuário e o entrega", async () => {
    api({
      "GET /api/auth/eu": hospedado,
      "GET /api/assistida/sessao": { ativa: false },
      "POST /api/extensao/parear": { token: "sch_e_TOKEN", servidor: "https://servidor.exemplo" },
    });
    const msgs = extensaoFalsa({ pareado: false });
    tela();
    expect(await screen.findByText("Extensão conectada (v2.0.0)")).toBeInTheDocument();
    expect(ultima("POST", "/api/extensao/parear")).toBeTruthy();
    expect(ultima("GET", "/api/assistida/token")).toBeUndefined(); // o token global só existe no modo local
    const entrega = msgs.find((m) => m.tipo === "configurar");
    expect(entrega.token).toBe("sch_e_TOKEN");
    expect(entrega.servidor).toBeUndefined(); // a página nunca tenta trocar o servidor da extensão
  });

  it("extensão já pareada: não gera token novo, só ajusta o recorte", async () => {
    api({ "GET /api/auth/eu": hospedado, "GET /api/assistida/sessao": { ativa: false } });
    const msgs = extensaoFalsa({ pareado: true });
    tela();
    expect(await screen.findByText("Extensão conectada (v2.0.0)")).toBeInTheDocument();
    expect(ultima("POST", "/api/extensao/parear")).toBeUndefined();
    expect(msgs.find((m) => m.tipo === "configurar")).toMatchObject({ recorteTopoPx: 0 });
  });

  it("extensão configurada para outro servidor: explica como corrigir nas opções", async () => {
    api({
      "GET /api/auth/eu": hospedado,
      "GET /api/assistida/sessao": { ativa: false },
      "POST /api/extensao/parear": { token: "t", servidor: "x" },
    });
    extensaoFalsa({ pareado: false, configurar: { ok: false, erro: "Esta página não é o servidor configurado na extensão." }, servidor: "https://outro.exemplo" });
    tela();
    expect(await screen.findByText("Extensão configurada para outro servidor")).toBeInTheDocument();
    expect(screen.getByText("https://outro.exemplo")).toBeInTheDocument();
    expect(screen.getByText(/opções da extensão/)).toBeInTheDocument();
  });

  it("modo local: pareia pelo token global e não mostra o aviso de privacidade do hospedado", async () => {
    api({
      "GET /api/auth/eu": local,
      "GET /api/assistida/sessao": { ativa: false },
      "GET /api/assistida/token": { token: "token-local", servidor: "http://127.0.0.1:5000" },
    });
    const msgs = extensaoFalsa({ pareado: false });
    tela();
    expect(await screen.findByText("Extensão conectada (v2.0.0)")).toBeInTheDocument();
    expect(msgs.find((m) => m.tipo === "configurar")).toMatchObject({ token: "token-local", servidor: "http://127.0.0.1:5000" });
    expect(screen.queryByText(/Privacidade:/)).not.toBeInTheDocument();
  });
});

describe("Coleta assistida: tela", () => {
  it("no modo hospedado avisa sobre nome/CEP nos prints e sobre o recorte", async () => {
    api({ "GET /api/auth/eu": hospedado, "GET /api/assistida/sessao": { ativa: false }, "POST /api/extensao/parear": { token: "t" } });
    extensaoFalsa({ pareado: true });
    tela();
    expect(await screen.findByText(/Privacidade:/)).toBeInTheDocument();
    expect(screen.getAllByText(/nome ou CEP/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Cortar do print o topo/)).toBeInTheDocument();
  });

  it("ao começar, mostra o que ficou fora da fila por estar em coleta por outra pessoa e abre o primeiro produto", async () => {
    const sessao = {
      ativa: true, execucao_id: 11, total: 1, concluidos: 0, proximo_produto_id: 5,
      itens: [{ produto_id: 5, nome: "Produto A", loja: "Magalu", url: "https://www.magazineluiza.com.br/a/p/1/", concluido: false, pulado: false, coleta: null }],
      em_coleta_por_outros: [{ produto_id: 6, produto: "Produto B", por: "Ana" }],
    };
    api({
      "GET /api/auth/eu": hospedado,
      "GET /api/assistida/sessao": { ativa: false },
      "POST /api/assistida/iniciar": sessao,
    });
    const msgs = extensaoFalsa({ pareado: true });
    const u = userEvent.setup();
    tela();
    await u.click(await screen.findByRole("button", { name: "Começar coleta assistida" }));
    expect(await screen.findByText(/Produto B \(Ana\)/)).toBeInTheDocument();
    await waitFor(() => expect(msgs.find((m) => m.tipo === "navegar")).toMatchObject({ produtoId: 5, execucaoId: 11 }));
  });

  it("mostra o erro de intervalo/limite devolvido pela extensão (servidor negou abrir a página)", async () => {
    api({
      "GET /api/auth/eu": hospedado,
      "GET /api/assistida/sessao": { ativa: false },
      "POST /api/assistida/iniciar": {
        ativa: true, execucao_id: 1, total: 1, concluidos: 0, proximo_produto_id: 5,
        itens: [{ produto_id: 5, nome: "Produto A", loja: "Magalu", url: "https://www.magazineluiza.com.br/a/p/1/", concluido: false, pulado: false, coleta: null }],
      },
    });
    const responder = (m, resposta) =>
      window.dispatchEvent(new MessageEvent("message", {
        data: { origem: "searching-ext", tipo: "resposta", id: m.id, tipoOriginal: m.tipo, ...resposta }, origin: window.location.origin, source: window,
      }));
    vi.spyOn(window, "postMessage").mockImplementation((m) => {
      if (!m || m.origem !== "searching-app") return;
      if (m.tipo === "ping") responder(m, { ok: true, versao: "2.0.0", pareado: true, servidor: "s" });
      else if (m.tipo === "configurar") responder(m, { ok: true });
      else if (m.tipo === "navegar") responder(m, { ok: false, erro: "aguarde", aguardarMs: 2500 });
    });
    const u = userEvent.setup();
    tela();
    await u.click(await screen.findByRole("button", { name: "Começar coleta assistida" }));
    expect(await screen.findByText(/Calma: aguarde 3 s/)).toBeInTheDocument();
  });
});
