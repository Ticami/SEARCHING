// SEARCHING - Coleta assistida (service worker).
// A cada "navegar" (disparado por um clique seu na tela do SEARCHING): abre o produto na aba dedicada,
// tira o print, lê a página, tenta abrir o menu de pagamento para ler o cartão 1x e envia tudo ao servidor local.
// Não abre links por conta própria, não resolve captcha e não tenta esconder que é uma extensão.
// Modo hospedado: o servidor (HTTPS) é fixado na página de opções; o token é por usuário e revogável.

const VERSAO = chrome.runtime.getManifest().version;
const SERVIDOR_PADRAO = "http://127.0.0.1:5000";
const INTERVALO_MINIMO_MS = 3000; // proteção: nunca mais de uma página a cada 3 s, mesmo que a tela peça
const ESPERA_CARGA_MS = 45000;
const HOSTS_PERMITIDOS = ["magazineluiza.com.br", "magazinevoce.com.br"]; // a extensão só navega por aqui

let ultimaNavegacao = 0;
let ocupado = false;
let alvo = { tabId: null, windowId: null };

// O service worker do MV3 é encerrado quando fica ocioso e as variáveis acima somem. A aba dedicada e o instante da última
// navegação ficam também em chrome.storage.session (dura enquanto o navegador estiver aberto), para o worker reaproveitar a
// MESMA janela depois de acordar em vez de abrir outra. O intervalo mínimo de 3 s continua sendo imposto também pelo servidor.
const memoria = chrome.storage.session || chrome.storage.local;
const CHAVE_ALVO = "abaDedicada";

async function restaurarEstado() {
  if (alvo.tabId != null) return;
  try {
    const salvo = (await memoria.get({ [CHAVE_ALVO]: null }))[CHAVE_ALVO];
    if (salvo && salvo.tabId != null) {
      alvo = { tabId: salvo.tabId, windowId: salvo.windowId };
      ultimaNavegacao = Math.max(ultimaNavegacao, salvo.ultimaNavegacao || 0);
    }
  } catch { /* sem storage: segue só com a memória */ }
}

async function gravarEstado() {
  try {
    await memoria.set({ [CHAVE_ALVO]: { tabId: alvo.tabId, windowId: alvo.windowId, ultimaNavegacao } });
  } catch { /* idem */ }
}

// se a pessoa fechar a aba dedicada, esquece-a (a próxima captura cria uma janela nova)
chrome.tabs.onRemoved.addListener(async (tabId) => {
  await restaurarEstado();
  if (alvo.tabId === tabId) {
    alvo = { tabId: null, windowId: null };
    await gravarEstado();
  }
});

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

function hostPermitido(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") return false;
    return HOSTS_PERMITIDOS.some((h) => u.hostname === h || u.hostname.endsWith("." + h));
  } catch {
    return false;
  }
}

async function config() {
  const c = await chrome.storage.local.get({ token: null, servidor: SERVIDOR_PADRAO, recorteTopoPx: 0 });
  return c;
}

const HOSTS_LOCAIS = ["127.0.0.1", "localhost"];

// O servidor precisa ser HTTPS; http só vale para o próprio computador (modo local).
function servidorValido(url) {
  try {
    const u = new URL(url);
    if (u.protocol === "https:") return true;
    return u.protocol === "http:" && HOSTS_LOCAIS.includes(u.hostname);
  } catch {
    return false;
  }
}

const origemDe = (url) => new URL(url).origin;
const ehLocal = (url) => HOSTS_LOCAIS.includes(new URL(url).hostname);

// Antes de abrir qualquer página, o servidor confere sessão, intervalo mínimo, limite da loja e quem está coletando o produto.
async function autorizarNoServidor(cfg, cmd) {
  const resp = await fetch(`${cfg.servidor}/api/assistida/autorizar`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Searching-Token": cfg.token, "X-Searching-Ext-Versao": VERSAO },
    body: JSON.stringify({ execucao_id: cmd.execucaoId, produto_id: cmd.produtoId }),
  });
  const corpo = await resp.json().catch(() => ({}));
  if (resp.status === 401) {
    await chrome.storage.local.set({ token: null }); // revogado ou inválido: força um novo pareamento
    throw new Error("O servidor não aceita mais este pareamento (token revogado). Abra a tela Coleta assistida e pareie de novo.");
  }
  if (!resp.ok) throw new Error(corpo.error || `O servidor recusou abrir a página (${resp.status}).`);
}

function avisar(appTabId, dados) {
  if (appTabId == null) return;
  chrome.tabs.sendMessage(appTabId, { evento: "etapa", ...dados }).catch(() => {});
}

// ---------- aba dedicada ----------
async function garantirAba() {
  await restaurarEstado();
  if (alvo.tabId != null) {
    try {
      const t = await chrome.tabs.get(alvo.tabId); // confirma que a aba ainda existe antes de reaproveitar
      alvo.windowId = t.windowId;
      await gravarEstado();
      return alvo;
    } catch {
      alvo = { tabId: null, windowId: null };
    }
  }
  // primeira vez (ou a aba foi fechada): janela própria, para você arrastar para o outro monitor e deixar lá
  const janela = await chrome.windows.create({ url: "about:blank", focused: false, state: "normal", width: 1280, height: 900 });
  alvo = { tabId: janela.tabs[0].id, windowId: janela.id };
  await gravarEstado();
  return alvo;
}

function aguardarCarga(tabId, limiteMs) {
  return new Promise((resolve, reject) => {
    const limite = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(ouvinte);
      reject(new Error("A página demorou demais para carregar."));
    }, limiteMs);
    function ouvinte(id, info) {
      if (id === tabId && info.status === "complete") {
        clearTimeout(limite);
        chrome.tabs.onUpdated.removeListener(ouvinte);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(ouvinte);
  });
}

// ---------- funções injetadas na página ----------
function lerPagina() {
  return {
    html: document.documentElement.outerHTML,
    url: location.href,
    titulo: document.title,
    dpr: window.devicePixelRatio || 1,
  };
}

async function aguardarConteudo() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t0 = Date.now();
  // espera o título do produto ou o preço aparecerem (a página termina de montar depois do "load")
  while (Date.now() - t0 < 9000) {
    if (document.querySelector("[data-testid='price-value'], h1")) break;
    await sleep(200);
  }
  await sleep(1200);
  return true;
}

async function abrirMenuCartao() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const esperar = async (fn, ms = 7000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      const v = fn();
      if (v) return v;
      await sleep(150);
    }
    return null;
  };
  const botao = document.querySelector("div[data-testid='rave-payment-card-link'][role='button']");
  if (!botao) return { ok: false, motivo: "O menu 'Ver opções de pagamento' não foi encontrado na página." };
  botao.scrollIntoView({ block: "center" });
  botao.click();
  const aba = await esperar(() => document.querySelector("span[data-testid='tab-header-item-Cartão de crédito']"));
  if (!aba) return { ok: false, motivo: "A aba 'Cartão de crédito' não apareceu." };
  (aba.closest("[role='tab']") || aba).click();
  const linha = await esperar(() => document.querySelector("tr[data-testid*='payment-table-Cartão de crédito-item']"));
  if (!linha) return { ok: false, motivo: "A tabela de parcelas não apareceu." };
  await sleep(500);
  return { ok: true, html: document.documentElement.outerHTML };
}

function fecharMenu() {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  return true;
}

// ---------- captura ----------
function paraBase64(buffer) {
  let bin = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function recortarTopo(dataUrl, topoPx, dpr) {
  const corte = Math.round((topoPx || 0) * (dpr || 1));
  if (!corte) return dataUrl;
  const img = await createImageBitmap(await (await fetch(dataUrl)).blob());
  if (corte >= img.height) return dataUrl;
  const canvas = new OffscreenCanvas(img.width, img.height - corte);
  canvas.getContext("2d").drawImage(img, 0, corte, img.width, img.height - corte, 0, 0, img.width, img.height - corte);
  const blob = await canvas.convertToBlob({ type: "image/png" });
  return "data:image/png;base64," + paraBase64(await blob.arrayBuffer());
}

async function executar(tabId, func) {
  const [r] = await chrome.scripting.executeScript({ target: { tabId }, func });
  return r ? r.result : null;
}

async function capturar(cmd, appTabId) {
  const cfg = await config();
  if (!cfg.token) throw new Error("Extensão sem token: abra a tela Coleta assistida do SEARCHING para parear.");
  const etapa = (nome, detalhe) => avisar(appTabId, { seq: cmd.seq, etapa: nome, detalhe });

  etapa("autorizando");
  await autorizarNoServidor(cfg, cmd);

  const { tabId, windowId } = await garantirAba();
  etapa("navegando", cmd.url);
  await chrome.tabs.update(tabId, { url: cmd.url, active: true });
  await aguardarCarga(tabId, ESPERA_CARGA_MS);

  etapa("lendo");
  await executar(tabId, aguardarConteudo);
  const pagina = await executar(tabId, lerPagina);

  // print ANTES de abrir qualquer menu: é a evidência da página como ela aparece
  try {
    const janela = await chrome.windows.get(windowId);
    if (janela.state === "minimized") await chrome.windows.update(windowId, { state: "normal" });
  } catch { /* janela fechada: o erro aparece na captura */ }
  await chrome.tabs.update(tabId, { active: true });
  await dormir(350);
  let screenshot = null;
  try {
    screenshot = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
    screenshot = await recortarTopo(screenshot, cfg.recorteTopoPx, pagina.dpr);
  } catch (e) {
    etapa("aviso", "Não consegui tirar o print: " + (e.message || e));
  }

  // cartão 1x: só vale a pena se a página parece ser a do produto (não a de bloqueio)
  let htmlModal = null;
  if (!/Não é possível acessar a página|Erro 403|captcha/i.test(pagina.titulo + " " + pagina.html.slice(0, 4000))) {
    etapa("menu", "abrindo opções de pagamento");
    try {
      const menu = await executar(tabId, abrirMenuCartao);
      if (menu && menu.ok) htmlModal = menu.html;
      else etapa("aviso", (menu && menu.motivo) || "Não consegui abrir o menu de pagamento.");
      await executar(tabId, fecharMenu);
    } catch (e) {
      etapa("aviso", "Menu de pagamento: " + (e.message || e));
    }
  }

  etapa("enviando");
  const resp = await fetch(`${cfg.servidor}/api/assistida/captura`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Searching-Token": cfg.token, "X-Searching-Ext-Versao": VERSAO },
    body: JSON.stringify({
      execucao_id: cmd.execucaoId,
      produto_id: cmd.produtoId,
      url_final: pagina.url,
      html: pagina.html,
      html_modal: htmlModal,
      screenshot,
    }),
  });
  const corpo = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(corpo.error || `O servidor respondeu ${resp.status}`);
  avisar(appTabId, { seq: cmd.seq, etapa: "pronto", resultado: corpo });
}

async function navegar(cmd, sender) {
  await restaurarEstado();
  const agora = Date.now();
  if (ocupado) return { ok: false, erro: "Ainda estou lendo a página anterior." };
  if (!hostPermitido(cmd.url)) return { ok: false, erro: "Endereço fora das lojas permitidas pela extensão." };
  const espera = INTERVALO_MINIMO_MS - (agora - ultimaNavegacao);
  if (espera > 0) return { ok: false, erro: "aguarde", aguardarMs: espera };

  ocupado = true;
  ultimaNavegacao = agora;
  await gravarEstado();
  const appTabId = sender.tab ? sender.tab.id : null;
  // mantém o service worker vivo enquanto a captura roda
  const vivo = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);
  capturar(cmd, appTabId)
    .catch((e) => avisar(appTabId, { seq: cmd.seq, etapa: "erro", detalhe: e.message || String(e) }))
    .finally(() => {
      clearInterval(vivo);
      ocupado = false;
    });
  return { ok: true };
}

chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  (async () => {
    const daPaginaDeOpcoes = !!sender.url && sender.url.startsWith(chrome.runtime.getURL("opcoes.html"));
    if (msg.tipo === "ping") {
      await restaurarEstado();
      const c = await config();
      return { ok: true, versao: VERSAO, pareado: !!c.token, janela: alvo.tabId != null, servidor: c.servidor };
    }
    if (msg.tipo === "configurar") {
      // Só a página do SEARCHING do servidor JÁ FIXADO pode entregar o token; ela nunca troca o endereço do servidor.
      // (Quem muda o servidor é a página de opções da extensão, por ação explícita da pessoa.)
      const c = await config();
      const origemDaPagina = sender.url ? origemDe(sender.url) : null;
      const doServidorFixado = origemDaPagina && servidorValido(c.servidor) && origemDaPagina === origemDe(c.servidor);
      const localComLocal = origemDaPagina && ehLocal(origemDaPagina) && ehLocal(c.servidor);
      if (!daPaginaDeOpcoes && !doServidorFixado && !localComLocal) {
        return { ok: false, erro: "Esta página não é o servidor configurado na extensão." };
      }
      const novo = {};
      if (msg.token !== undefined) novo.token = String(msg.token || "");
      if (msg.recorteTopoPx !== undefined) novo.recorteTopoPx = Math.max(0, Math.min(400, Number(msg.recorteTopoPx) || 0));
      // modo local: o pareamento automático informa a porta do servidor local (sempre loopback)
      if (localComLocal && msg.servidor && servidorValido(msg.servidor) && ehLocal(msg.servidor)) novo.servidor = origemDe(msg.servidor);
      if (daPaginaDeOpcoes && msg.servidor !== undefined && servidorValido(msg.servidor)) {
        if (origemDe(msg.servidor) !== origemDe(c.servidor)) novo.token = null; // outro servidor: o token antigo não vale
        novo.servidor = origemDe(msg.servidor);
      }
      await chrome.storage.local.set(novo);
      return { ok: true };
    }
    if (msg.tipo === "navegar") return navegar(msg, sender);
    return { ok: false, erro: "Mensagem desconhecida." };
  })().then(responder);
  return true; // resposta assíncrona
});
