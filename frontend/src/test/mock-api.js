// fetch simulado por tabela de rotas ("METODO /caminho" -> resposta). Instalado pelo setup.js antes de qualquer import da aplicação.
import { vi } from "vitest";

export const chamadas = [];
let rotas = {};

/** Define respostas da API. Valor: objeto/lista (200), [status, objeto] ou função (url, {corpo}) => uma das duas formas. */
export function api(novas) {
  rotas = { ...rotas, ...novas };
}

export function zerar() {
  rotas = {};
  chamadas.length = 0;
}

export function instalarFetch() {
  globalThis.fetch = vi.fn(async (entrada, init = {}) => {
    const url = typeof entrada === "string" ? entrada : entrada.url;
    const metodo = (init.method || "GET").toUpperCase();
    const corpo = init.body ? JSON.parse(init.body) : undefined;
    chamadas.push({ metodo, url, corpo, headers: init.headers || {} });
    const chave = `${metodo} ${url.split("?")[0]}`;
    let resposta = rotas[chave];
    if (typeof resposta === "function") resposta = resposta(url, { ...init, corpo });
    if (resposta === undefined) resposta = [404, { error: `sem rota simulada: ${chave}` }];
    const [status, json] = Array.isArray(resposta) && typeof resposta[0] === "number" ? resposta : [200, resposta];
    return { ok: status >= 200 && status < 300, status, json: async () => json };
  });
}
