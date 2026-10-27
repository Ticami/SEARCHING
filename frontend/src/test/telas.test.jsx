import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, chamadas } from "./mock-api.js";
import { AuthProvider, useAuth } from "../auth.jsx";
import Alerts from "../pages/Alerts.jsx";
import LinkHistory from "../pages/LinkHistory.jsx";

const eu = (papel, modo = "hospedado") => ({
  modo, usuario: { id: 1, email: "u@x.com", nome: "U", papel, ativo: true }, csrf: "t", atribuidos: [],
});
function SoDepoisDoLogin({ children }) {
  const { carregando } = useAuth();
  return carregando ? null : children;
}
const tela = (filho) => render(<MemoryRouter><AuthProvider><SoDepoisDoLogin>{filho}</SoDepoisDoLogin></AuthProvider></MemoryRouter>);
const ultima = (metodo, url) => [...chamadas].reverse().find((c) => c.metodo === metodo && c.url.startsWith(url));

afterEach(() => vi.restoreAllMocks());

describe("Histórico de trocas de link", () => {
  const trocas = [
    { id: 1, produto_id: 7, produto: "Galaxy S25", url_antiga: "https://a/p/1/", url_nova: "https://a/p/2/", motivo: "link quebrado", origem: "automatico", nota_confianca: 0.93, em: "2026-10-24T10:00:00", revertivel: true },
    { id: 2, produto_id: 7, produto: "Galaxy S25", url_antiga: "https://a/p/0/", url_nova: "https://a/p/1/", motivo: "", origem: "manual", nota_confianca: null, em: "2026-10-20T10:00:00", revertivel: false },
  ];

  it("lista as trocas e deixa reverter só a mais recente (admin)", async () => {
    api({ "GET /api/auth/eu": eu("admin"), "GET /api/links/historico": trocas, "POST /api/links/historico/1/reverter": { message: "Link revertido." } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const u = userEvent.setup();
    tela(<LinkHistory />);
    expect(await screen.findByText("Automática (recuperação) · link quebrado")).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument();
    const botoes = screen.getAllByRole("button", { name: /^Reverter a troca/ });
    expect(botoes[0]).toBeEnabled();
    expect(botoes[1]).toBeDisabled();
    await u.click(botoes[0]);
    expect(await screen.findByText("Link revertido.")).toBeInTheDocument();
    expect(ultima("POST", "/api/links/historico/1/reverter")).toBeTruthy();
  });

  it("quem não é admin não consegue reverter", async () => {
    api({ "GET /api/auth/eu": eu("coletor"), "GET /api/links/historico": trocas });
    tela(<LinkHistory />);
    await screen.findByText("Automática (recuperação) · link quebrado");
    screen.getAllByRole("button", { name: /^Reverter a troca/ }).forEach((b) => expect(b).toBeDisabled());
  });

  it("mostra o estado vazio", async () => {
    api({ "GET /api/auth/eu": eu("leitor"), "GET /api/links/historico": [] });
    tela(<LinkHistory />);
    expect(await screen.findByText("Nenhuma troca de link registrada ainda.")).toBeInTheDocument();
  });
});

describe("Alertas: destinatários, resumo semanal e assinaturas", () => {
  const dados = {
    smtp: { configurado: true, remetente: "r@x.com", destinatarios: ["env@x.com"], servidor: "smtp:587" },
    destinatarios: { configurados: ["gestor@x.com"] },
    config: { alertas_ativos: "1", alerta_pct_queda: "5", alerta_degrau_pct: "2", alerta_base_preco: "pix", alerta_base_comparacao: "ultimo", alerta_dias_janela: "30", resumo_diario_email: "0", resumo_semanal_email: "0" },
    alertas: [],
  };
  const regras = [{ produto_id: 7, nome: "Galaxy S25", loja: "Magalu", alerta_pct: null, alerta_base: null, alerta_preco_alvo: null }];
  const rotas = (papel, modo = "hospedado") => ({
    "GET /api/auth/eu": eu(papel, modo), "GET /api/alertas": dados, "GET /api/alertas/regras": regras, "GET /api/minhas-assinaturas": { produtos: [] },
  });

  it("admin edita a lista de destinatários e salva", async () => {
    api({ ...rotas("admin"), "PUT /api/alertas/destinatarios": { message: "Destinatários salvos.", configurados: ["a@x.com", "b@x.com"] } });
    const u = userEvent.setup();
    tela(<Alerts />);
    const campo = await screen.findByLabelText(/Destinatários dos alertas/);
    expect(campo).toHaveValue("gestor@x.com");
    await u.clear(campo);
    await u.type(campo, "a@x.com, b@x.com");
    await u.click(screen.getByRole("button", { name: "Salvar destinatários" }));
    expect(await screen.findByText("Destinatários salvos.")).toBeInTheDocument();
    expect(ultima("PUT", "/api/alertas/destinatarios").corpo).toEqual({ destinatarios: "a@x.com, b@x.com" });
    expect(campo).toHaveValue("a@x.com, b@x.com");
  });

  it("leitor e coletor veem a lista, mas não a editam", async () => {
    api(rotas("coletor"));
    tela(<Alerts />);
    expect(await screen.findByLabelText(/Destinatários dos alertas/)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Salvar destinatários" })).toBeDisabled();
  });

  it("liga o resumo semanal e salva o padrão", async () => {
    api({ ...rotas("admin"), "PUT /api/alertas/config": { message: "Configuração de alertas salva.", config: { ...dados.config, resumo_semanal_email: "1" } } });
    const u = userEvent.setup();
    tela(<Alerts />);
    await u.click(await screen.findByRole("checkbox", { name: /Enviar resumo semanal em Excel/ }));
    await u.click(screen.getByRole("button", { name: "Salvar padrão" }));
    await waitFor(() => expect(ultima("PUT", "/api/alertas/config").corpo.resumo_semanal_email).toBe("1"));
  });

  it("coletor assina um produto pelo próprio e-mail; leitor não pode", async () => {
    api({ ...rotas("coletor"), "PUT /api/minhas-assinaturas": { produtos: [7] } });
    const u = userEvent.setup();
    const { unmount } = tela(<Alerts />);
    const caixa = await screen.findByRole("checkbox", { name: /Receber alertas de Galaxy S25/ });
    expect(caixa).toBeEnabled();
    await u.click(caixa);
    await waitFor(() => expect(ultima("PUT", "/api/minhas-assinaturas").corpo).toEqual({ produtos: [7] }));
    unmount();

    api(rotas("leitor"));
    tela(<Alerts />);
    expect(await screen.findByRole("checkbox", { name: /Receber alertas de Galaxy S25/ })).toBeDisabled();
  });

  it("no modo local não existe a coluna de assinatura", async () => {
    api(rotas("admin", "local"));
    tela(<Alerts />);
    await screen.findByText("Galaxy S25");
    expect(screen.queryByText("Receber no meu e-mail")).not.toBeInTheDocument();
    expect(within(screen.getAllByRole("table")[0]).queryByRole("checkbox")).toBeNull();
  });
});
