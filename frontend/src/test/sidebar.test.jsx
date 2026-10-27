import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./mock-api.js";
import App from "../App.jsx";
import { AuthProvider } from "../auth.jsx";
import { BotaoSidebar, lerRecolhida, useSidebarRecolhida } from "../sidebar.jsx";

const CHAVE = "searching_sidebar_recolhida";

function Exemplo() {
  const [recolhida, alternar] = useSidebarRecolhida();
  return (
    <div className={`layout${recolhida ? " sidebar-recolhida" : ""}`} data-testid="layout">
      <BotaoSidebar recolhida={recolhida} onAlternar={alternar} controla="menu" />
      <nav id="menu" hidden={recolhida}>menu</nav>
    </div>
  );
}

const celular = (ativo) =>
  vi.spyOn(window, "matchMedia").mockImplementation((q) => ({ matches: ativo, media: q, addEventListener() {}, removeEventListener() {} }));

afterEach(() => vi.restoreAllMocks());

describe("Botão do menu lateral", () => {
  it("começa expandido, com aria-expanded e rótulo, e recolhe/expande ao clicar", async () => {
    const u = userEvent.setup();
    render(<Exemplo />);
    const botao = screen.getByRole("button", { name: "Recolher o menu lateral" });
    expect(botao).toHaveAttribute("aria-expanded", "true");
    expect(botao).toHaveAttribute("aria-controls", "menu");
    await u.click(botao);
    const aberto = screen.getByRole("button", { name: "Expandir o menu lateral" });
    expect(aberto).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("layout")).toHaveClass("sidebar-recolhida");
    expect(screen.getByText("menu")).not.toBeVisible();
    await u.click(aberto);
    expect(screen.getByRole("button", { name: "Recolher o menu lateral" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("menu")).toBeVisible();
  });

  it("funciona só pelo teclado (Tab, Enter e Espaço)", async () => {
    const u = userEvent.setup();
    render(<Exemplo />);
    await u.tab();
    expect(screen.getByRole("button", { name: /menu lateral/ })).toHaveFocus();
    await u.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Expandir o menu lateral" })).toHaveAttribute("aria-expanded", "false");
    await u.keyboard(" ");
    expect(screen.getByRole("button", { name: "Recolher o menu lateral" })).toHaveAttribute("aria-expanded", "true");
  });

  it("guarda a escolha no localStorage e a restaura", async () => {
    const u = userEvent.setup();
    const { unmount } = render(<Exemplo />);
    await u.click(screen.getByRole("button", { name: "Recolher o menu lateral" }));
    expect(window.localStorage.getItem(CHAVE)).toBe("1");
    unmount();
    render(<Exemplo />); // "recarregou a página"
    expect(screen.getByRole("button", { name: "Expandir o menu lateral" })).toHaveAttribute("aria-expanded", "false");
    await u.click(screen.getByRole("button", { name: "Expandir o menu lateral" }));
    expect(window.localStorage.getItem(CHAVE)).toBe("0");
  });

  it("em celular começa recolhido, mas a escolha salva vale mais que o padrão", () => {
    celular(true);
    expect(lerRecolhida()).toBe(true);
    window.localStorage.setItem(CHAVE, "0");
    expect(lerRecolhida()).toBe(false);
  });

  it("em computador começa expandido", () => {
    celular(false);
    expect(lerRecolhida()).toBe(false);
  });

  it("sem localStorage (bloqueado) a tela continua funcionando", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("bloqueado"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("bloqueado"); });
    const u = userEvent.setup();
    render(<Exemplo />);
    await u.click(screen.getByRole("button", { name: "Recolher o menu lateral" }));
    expect(screen.getByRole("button", { name: "Expandir o menu lateral" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Menu lateral no App", () => {
  it("o botão esconde o menu principal e o devolve", async () => {
    api({
      "GET /api/auth/eu": { modo: "local", usuario: { id: null, email: "local", nome: "Uso local", papel: "admin" }, csrf: null, atribuidos: null },
      "GET /api/revisoes": [],
    });
    const u = userEvent.setup();
    render(<AuthProvider><App /></AuthProvider>);
    const menu = await screen.findByRole("navigation", { name: "Menu principal" });
    expect(menu).toBeVisible();
    await u.click(screen.getByRole("button", { name: "Recolher o menu lateral" }));
    expect(screen.queryByRole("navigation", { name: "Menu principal" })).not.toBeInTheDocument(); // oculto: fora da árvore de acessibilidade
    expect(document.querySelector(".layout")).toHaveClass("sidebar-recolhida");
    await u.click(screen.getByRole("button", { name: "Expandir o menu lateral" }));
    expect(screen.getByRole("navigation", { name: "Menu principal" })).toBeVisible();
  });
});
