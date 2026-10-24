// Página de opções: único lugar que muda o endereço do servidor (ação explícita da pessoa).
const $ = (id) => document.getElementById(id);
const dizer = (texto) => { $("estado").textContent = texto; };
const ID_PONTE = "ponte-servidor";

function servidorValido(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || (u.protocol === "http:" && ["127.0.0.1", "localhost"].includes(u.hostname));
  } catch {
    return false;
  }
}

// O ponte.js precisa rodar na página do SEARCHING hospedado; o manifest só conhece o endereço local.
async function registrarPonte(origem) {
  try { await chrome.scripting.unregisterContentScripts({ ids: [ID_PONTE] }); } catch { /* nada registrado ainda */ }
  await chrome.scripting.registerContentScripts([{
    id: ID_PONTE, matches: [origem + "/*"], js: ["ponte.js"], runAt: "document_start", persistAcrossSessions: true,
  }]);
}

async function carregar() {
  const c = await chrome.storage.local.get({ servidor: "", token: null, recorteTopoPx: 0 });
  $("servidor").value = c.servidor || "";
  $("recorte").value = c.recorteTopoPx || 0;
  dizer(c.token ? "Pareada com " + c.servidor : "Ainda não pareada.");
}

$("salvar").addEventListener("click", async () => {
  const servidor = $("servidor").value.trim().replace(/\/+$/, "");
  if (!servidorValido(servidor)) return dizer("Endereço inválido: use https://… (ou http://127.0.0.1:porta neste computador).");
  const msg = { tipo: "configurar", servidor, recorteTopoPx: Number($("recorte").value) || 0 };
  if ($("token").value.trim()) msg.token = $("token").value.trim();
  const r = await chrome.runtime.sendMessage(msg);
  if (!r || !r.ok) return dizer((r && r.erro) || "Não consegui salvar.");
  await registrarPonte(new URL(servidor).origin);
  $("token").value = "";
  await carregar();
});

$("desparear").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ tipo: "configurar", token: "" });
  await carregar();
});

carregar();
