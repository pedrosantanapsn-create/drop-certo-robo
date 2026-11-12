// Drop Certo - Ajudante (extensão). Roda no SEU navegador normal, já logado no Mercado Livre.
// De minuto em minuto olha se o robô pediu algum link; se pediu, abre o "Gerador de links" de
// afiliados numa aba, gera o meli.la e devolve ao robô. Não guarda nem vê a sua senha do ML.

const SUPABASE = "https://euctzxrnxeizgtnmlesn.supabase.co";
const CHAVE_PUBLICA = "sb_publishable_SMh-znhRJUnZCjBi4DH3hQ_yvkmIY6X";   // a mesma do site (pública)
const TABELA = SUPABASE + "/rest/v1/ajudante_pedidos";
const GERADOR = "https://www.mercadolivre.com.br/afiliados/linkbuilder";
const MAX_POR_HORA = 20;
const MAX_TENTATIVAS = 3;
const PAUSA_ENTRE_LINKS_MS = 20000;

let trabalhando = false;

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create("olhar", { periodInMinutes: 1 }));
chrome.runtime.onStartup.addListener(() => chrome.alarms.create("olhar", { periodInMinutes: 1 }));
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "olhar") rodada(); });
chrome.runtime.onMessage.addListener((msg, _de, responder) => {
  if (msg && msg.tipo === "testarBusca") {
    executarNaAba(msg.url, naPaginaBusca, [msg.loja]).then((r) => responder(r)).catch((e) => responder({ itens: [], erro: String(e) }));
    return true;
  }
  if (msg && msg.tipo === "testar") {
    gerarMeli(msg.url).then((r) => responder(r)).catch((e) => responder({ link: "", erro: String(e) }));
    return true;                                   // resposta assíncrona
  }
  if (msg && msg.tipo === "agora") { rodada().then(() => responder({ ok: true })); return true; }
});

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

async function guardar(obj) { await chrome.storage.local.set(obj); }
async function ler(chaves) { return chrome.storage.local.get(chaves); }

async function cabecalhos(extra) {
  const { senha } = await ler(["senha"]);
  return Object.assign({ apikey: CHAVE_PUBLICA, Authorization: "Bearer " + CHAVE_PUBLICA,
                         "x-ajudante-chave": senha || "", "Content-Type": "application/json" }, extra || {});
}

async function sinalDeVida(precisaLogin) {
  const corpo = { loja: "_sistema", chave: "_batimento", status: "sinal",
                  dados: { precisa_login: !!precisaLogin, onde: "extensao" }, feito_em: new Date().toISOString() };
  let r = await fetch(TABELA + "?chave=eq._batimento", {
    method: "PATCH", headers: await cabecalhos({ Prefer: "return=representation" }), body: JSON.stringify(corpo) });
  if (r.ok && (await r.json()).length) return true;
  r = await fetch(TABELA, { method: "POST", headers: await cabecalhos(), body: JSON.stringify(corpo) });
  return r.ok || r.status === 409;                 // false = senha do ajudante errada (ou tabela não criada)
}

async function responder(id, campos) {
  campos.feito_em = new Date().toISOString();
  await fetch(TABELA + "?id=eq." + id, { method: "PATCH", headers: await cabecalhos(), body: JSON.stringify(campos) });
}

function esperarCarregar(tabId, limiteMs) {
  return new Promise((resolver) => {
    const fim = setTimeout(() => { chrome.tabs.onUpdated.removeListener(ouvir); resolver(false); }, limiteMs);
    function ouvir(id, info) {
      if (id === tabId && info.status === "complete") {
        clearTimeout(fim); chrome.tabs.onUpdated.removeListener(ouvir); resolver(true);
      }
    }
    chrome.tabs.onUpdated.addListener(ouvir);
  });
}

// ---- Estas duas funções rodam DENTRO da página do Mercado Livre ----------------------------
async function naPaginaGerador(urlProduto) {
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const acharMeli = () => {
    const textos = [document.body ? document.body.innerText : ""];
    document.querySelectorAll("input, textarea").forEach((e) => textos.push(e.value || ""));
    for (const t of textos) { const m = t.match(/https?:\/\/meli\.la\/[A-Za-z0-9]+/); if (m) return m[0]; }
    return "";
  };
  let caixa = null;
  for (let i = 0; i < 30 && !caixa; i++) { caixa = document.querySelector("textarea"); if (!caixa) await esperar(500); }
  if (!caixa) return { link: "", erro: "não achei a caixa de URLs no gerador de links" };
  const definir = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  caixa.focus();
  definir.call(caixa, urlProduto);                  // o site é feito em React: precisa avisar a mudança
  caixa.dispatchEvent(new Event("input", { bubbles: true }));
  caixa.dispatchEvent(new Event("change", { bubbles: true }));
  let botao = null;
  for (let i = 0; i < 20; i++) {
    botao = [...document.querySelectorAll("button")].find((b) => /^\s*gerar\s*$/i.test(b.innerText || ""));
    if (botao && !botao.disabled) break;
    await esperar(500);
  }
  if (!botao) return { link: "", erro: "não achei o botão Gerar" };
  if (botao.disabled) return { link: "", erro: "o botão Gerar ficou apagado (o endereço do produto não foi aceito)" };
  botao.click();
  for (let i = 0; i < 40; i++) { const l = acharMeli(); if (l) return { link: l }; await esperar(500); }
  const aviso = (document.body.innerText.match(/(n[ãa]o (foi )?poss[ií]vel[^\n]{0,120}|erro[^\n]{0,120}|inv[áa]lid[^\n]{0,120})/i) || [""])[0];
  return { link: "", erro: "o gerador não devolveu o link" + (aviso ? " (" + aviso + ")" : "") };
}

async function naPaginaProduto() {
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const acharMeli = () => {
    for (const e of document.querySelectorAll("input, textarea")) {
      const m = (e.value || "").match(/https?:\/\/meli\.la\/[A-Za-z0-9]+/); if (m) return m[0];
    }
    return "";
  };
  let botao = null;
  for (let i = 0; i < 20 && !botao; i++) {
    botao = [...document.querySelectorAll("button, a")].find((b) => /^\s*compartilhar\s*$/i.test(b.innerText || "")
              && b.getBoundingClientRect().top < 140);              // o da barra preta de Afiliados, no topo
    if (!botao) await esperar(500);
  }
  if (!botao) return { link: "", erro: "não achei o botão Compartilhar da barra de Afiliados" };
  botao.click();
  for (let i = 0; i < 30; i++) { const l = acharMeli(); if (l) return { link: l }; await esperar(500); }
  return { link: "", erro: "a janela Gerar link não mostrou o meli.la" };
}

// Lê a lista de produtos de uma página de busca (Terabyte ou Amazon) do jeito que ela aparece para você.
async function naPaginaBusca(loja) {
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const num = (t) => { const m = String(t || "").match(/([\d.]+,\d{2})/); return m ? parseFloat(m[1].replace(/\./g, "").replace(",", ".")) : null; };
  await esperar(2500);
  window.scrollTo(0, 1500); await esperar(800); window.scrollTo(0, 0);     // carrega as fotos de baixo
  const itens = [];
  if (loja === "busca_amazon") {
    document.querySelectorAll('div[data-component-type="s-search-result"][data-asin]').forEach((c) => {
      const asin = c.getAttribute("data-asin");
      if (!asin || /patrocinado/i.test(c.innerText || "")) return;
      const nome = ((c.querySelector("h2") || {}).innerText || "").trim();
      const preco = num((c.querySelector(".a-price:not(.a-text-price) .a-offscreen") || {}).textContent);
      const antigo = num((c.querySelector(".a-price.a-text-price .a-offscreen") || {}).textContent);
      const img = c.querySelector("img.s-image");
      if (nome && preco) itens.push({ id: asin, nome, preco, preco_antigo: antigo, link: "https://www.amazon.com.br/dp/" + asin,
                                      imagem: img ? img.src : "" });
    });
  } else {
    const vistos = new Set();
    document.querySelectorAll('a[href*="/produto/"]').forEach((a) => {
      const href = a.href.split("?")[0].split("#")[0];
      if (vistos.has(href)) return;
      let cartao = a;
      for (let i = 0; i < 7; i++) {
        if (/R\$\s*\d/.test(cartao.innerText || "") && cartao.querySelector("img")) break;
        cartao = cartao.parentElement;
        if (!cartao) return;
      }
      const texto = cartao.innerText || "";
      if (!/R\$\s*\d/.test(texto)) return;
      if (new Set([...cartao.querySelectorAll('a[href*="/produto/"]')].map((x) => x.href.split("?")[0])).size > 1) return;
      if (/esgotad|indispon[ií]vel|avise-me|todos vendidos/i.test(texto)) return;
      const semParcelas = texto.replace(/\d+\s*x\s*(de\s*)?R\$\s*[\d.]+,\d{2}/gi, " ");
      const valores = [...semParcelas.matchAll(/R\$\s*([\d.]+,\d{2})/g)].map((m) => num(m[1])).filter(Boolean);
      if (!valores.length) return;
      const preco = Math.min(...valores), maior = Math.max(...valores);
      const img = cartao.querySelector("img");
      const nome = (a.getAttribute("title") || (img && img.getAttribute("alt")) || a.innerText || "").trim();
      if (!nome) return;
      vistos.add(href);
      itens.push({ id: href, nome, preco, preco_antigo: maior > preco ? maior : null, link: href,
                   imagem: img ? (img.getAttribute("data-src") || img.currentSrc || img.src || "") : "" });
    });
  }
  if (itens.length) return { itens: itens.slice(0, 24) };
  const exemplo = document.querySelector('a[href*="/produto/"], div[data-component-type="s-search-result"]');
  return { itens: [], erro: "não achei produtos na página (" + location.href.slice(0, 80) + ")",
           amostra: (exemplo ? (exemplo.closest("div") || exemplo).outerHTML : (document.body.innerText || "")).slice(0, 500) };
}
// ---------------------------------------------------------------------------------------------

async function executarNaAba(endereco, funcao, args) {
  const aba = await chrome.tabs.create({ url: endereco, active: false });
  try {
    await esperarCarregar(aba.id, 45000);
    const atual = await chrome.tabs.get(aba.id);
    if (/\/login|\/jms\/|registration|account-verification/i.test(atual.url || "")) {
      return { link: "", login: true, erro: "o Mercado Livre pediu login" };
    }
    await dormir(1500);
    const [res] = await chrome.scripting.executeScript({ target: { tabId: aba.id }, func: funcao, args: args || [] });
    return (res && res.result) || { link: "", erro: "a página não respondeu" };
  } catch (e) {
    return { link: "", erro: String(e).slice(0, 160) };
  } finally {
    try { await chrome.tabs.remove(aba.id); } catch (_) { /* aba já fechada */ }
  }
}

async function gerarMeli(urlProduto) {
  let r = await executarNaAba(GERADOR, naPaginaGerador, [urlProduto]);
  if (r.link || r.login) return r;
  const erroGerador = r.erro;
  r = await executarNaAba(urlProduto, naPaginaProduto, []);       // plano B: botão Compartilhar do produto
  if (!r.link && !r.login) r.erro = "gerador: " + erroGerador + " | produto: " + r.erro;
  return r;
}

async function rodada() {
  if (trabalhando) return;
  trabalhando = true;
  try {
    const { senha } = await ler(["senha"]);
    if (!senha) { await guardar({ estado: "Falta colar a senha do ajudante (clique no ícone da extensão)." }); return; }
    if (!(await sinalDeVida(false))) {
      await guardar({ estado: "A senha do ajudante não foi aceita. Confira se copiou certo." });
      chrome.action.setBadgeText({ text: "!" });
      return;
    }
    const r = await fetch(TABELA + "?status=eq.pendente&loja=in.(ml,busca_terabyte,busca_amazon)&select=id,loja,chave,url,dados&order=criado_em.asc&limit=3",
                          { headers: await cabecalhos() });
    const pedidos = r.ok ? await r.json() : [];
    let { feitos = [], total = 0 } = await ler(["feitos", "total"]);
    for (const p of pedidos) {
      feitos = feitos.filter((t) => Date.now() - t < 3600000);
      if (feitos.length >= MAX_POR_HORA) break;
      if (String(p.loja).startsWith("busca_")) {              // busca na Terabyte / Amazon
        const b = await executarNaAba(p.url, naPaginaBusca, [p.loja]);
        feitos.push(Date.now());
        const dados = p.dados || {};
        if (b.itens && b.itens.length) {
          dados.resultado = b.itens;
          await responder(p.id, { status: "pronto", dados });
          total += 1;
          await guardar({ ultimo: "busca: " + (dados.termo || "") + " (" + b.itens.length + " produtos)", ultimoQuando: Date.now(), total });
        } else {
          await responder(p.id, { status: "erro", erro: (b.erro || "sem resultado") + (b.amostra ? " | amostra: " + b.amostra : "") });
          await guardar({ ultimoErro: b.erro || "", ultimoErroQuando: Date.now() });
        }
        await guardar({ feitos });
        await dormir(PAUSA_ENTRE_LINKS_MS);
        continue;
      }
      const res = await gerarMeli(p.url);
      feitos.push(Date.now());
      if (res.login) {
        await sinalDeVida(true);
        chrome.action.setBadgeText({ text: "!" });
        await guardar({ estado: "O Mercado Livre pediu login. Entre na sua conta neste navegador.", feitos });
        return;
      }
      if (res.link) {
        await responder(p.id, { status: "pronto", link: res.link });
        total += 1;
        await guardar({ ultimo: res.link, ultimoQuando: Date.now(), total });
      } else {
        const dados = p.dados || {};
        dados.tentativas = (dados.tentativas || 0) + 1;
        if (dados.tentativas >= MAX_TENTATIVAS) await responder(p.id, { status: "erro", dados, erro: res.erro || "sem detalhe" });
        else await responder(p.id, { dados });
        await guardar({ ultimoErro: res.erro || "", ultimoErroQuando: Date.now() });
      }
      await guardar({ feitos });
      await dormir(PAUSA_ENTRE_LINKS_MS);
    }
    chrome.action.setBadgeText({ text: "" });
    await guardar({ estado: "Ligado. Última olhada: " + new Date().toLocaleTimeString("pt-BR"), feitos });
  } catch (e) {
    await guardar({ estado: "Sem conexão com o robô agora (" + String(e).slice(0, 80) + ")." });
  } finally {
    trabalhando = false;
  }
}
