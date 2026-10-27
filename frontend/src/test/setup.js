// Ambiente dos testes de interface. O fetch simulado é instalado ANTES de qualquer import da aplicação
// (o auth.jsx embrulha window.fetch ao ser carregado).
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { instalarFetch, zerar } from "./mock-api.js";

instalarFetch();

beforeEach(() => {
  zerar();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});
