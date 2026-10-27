import React, { useCallback, useState } from "react";

const CHAVE = "searching_sidebar_recolhida";

/** Lê a escolha salva ("1" recolhida, "0" aberta). Sem escolha: começa recolhida em tela de celular. Sem localStorage: funciona igual. */
export function lerRecolhida() {
  try {
    const salvo = window.localStorage.getItem(CHAVE);
    if (salvo === "1") return true;
    if (salvo === "0") return false;
  } catch {
    /* localStorage bloqueado (janela privada, política): segue com o padrão */
  }
  try {
    return typeof window.matchMedia === "function" && window.matchMedia("(max-width: 860px)").matches;
  } catch {
    return false;
  }
}

export function useSidebarRecolhida() {
  const [recolhida, setRecolhida] = useState(lerRecolhida);
  const alternar = useCallback(() => {
    setRecolhida((atual) => {
      const nova = !atual;
      try {
        window.localStorage.setItem(CHAVE, nova ? "1" : "0");
      } catch {
        /* sem localStorage a escolha vale só até recarregar */
      }
      return nova;
    });
  }, []);
  return [recolhida, alternar];
}

/** Botão de recolher/expandir o menu lateral (acessível por teclado: é um <button>). */
export function BotaoSidebar({ recolhida, onAlternar, controla }) {
  return (
    <button
      type="button"
      className="btn ghost sidebar-toggle"
      onClick={onAlternar}
      aria-expanded={!recolhida}
      aria-controls={controla}
      aria-label={recolhida ? "Expandir o menu lateral" : "Recolher o menu lateral"}
      title={recolhida ? "Expandir o menu" : "Recolher o menu"}
    >
      <span aria-hidden="true">{recolhida ? "»" : "«"}</span>
    </button>
  );
}
