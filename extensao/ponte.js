// Ponte entre a página do SEARCHING (localhost) e a extensão.
// Só repassa as mensagens que a própria página envia; a lógica fica no background.js.
const ORIGEM_APP = "searching-app";
const ORIGEM_EXT = "searching-ext";

function paraPagina(dados) {
  window.postMessage({ origem: ORIGEM_EXT, ...dados }, window.location.origin);
}

window.addEventListener("message", (e) => {
  // ignora o que não veio desta mesma página (nem de iframes ou de outros sites)
  if (e.source !== window || e.origin !== window.location.origin) return;
  const msg = e.data;
  if (!msg || msg.origem !== ORIGEM_APP || typeof msg.tipo !== "string") return;

  chrome.runtime.sendMessage(msg, (resposta) => {
    const erro = chrome.runtime.lastError ? chrome.runtime.lastError.message : null;
    paraPagina({ tipo: "resposta", id: msg.id, tipoOriginal: msg.tipo, ...(erro ? { ok: false, erro } : resposta) });
  });
});

// Andamento da captura (navegando, lendo, enviando, pronto, erro) enviado pelo background.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.evento) paraPagina({ tipo: "evento", ...msg });
});
