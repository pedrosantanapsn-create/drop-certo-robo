const el = (id) => document.getElementById(id);

async function mostrar() {
  const d = await chrome.storage.local.get(["estado", "senha", "ultimo", "ultimoQuando", "total", "ultimoErro", "ultimoErroQuando"]);
  el("estado").textContent = d.estado || (d.senha ? "Ligado. Esperando a primeira olhada (até 1 minuto)." : "Falta colar a senha do ajudante.");
  const linhas = [];
  if (d.total) linhas.push("Links gerados: " + d.total);
  if (d.ultimo) linhas.push("Último: " + d.ultimo + " (" + new Date(d.ultimoQuando).toLocaleString("pt-BR") + ")");
  if (d.ultimoErro) linhas.push("Último erro: " + d.ultimoErro + " (" + new Date(d.ultimoErroQuando).toLocaleString("pt-BR") + ")");
  el("resumo").textContent = linhas.join("\n") || "Nenhum link gerado ainda.";
  el("resumo").style.whiteSpace = "pre-wrap";
  if (d.senha) el("senha").placeholder = "Senha já salva (cole outra para trocar)";
}

el("salvar").addEventListener("click", async () => {
  const senha = el("senha").value.trim();
  if (senha.length < 20) { el("estado").textContent = "Essa senha parece incompleta."; return; }
  await chrome.storage.local.set({ senha, estado: "Senha salva. Conferindo…" });
  el("senha").value = "";
  chrome.runtime.sendMessage({ tipo: "agora" }, () => mostrar());
});

el("testar").addEventListener("click", () => {
  const url = el("url").value.trim();
  if (!/^https?:\/\/[^ ]*mercadoli[bv]re\.com/i.test(url)) {
    el("teste").hidden = false; el("teste").textContent = "Cole o endereço de um produto do Mercado Livre."; return;
  }
  el("teste").hidden = false;
  el("teste").textContent = "Gerando… (abre uma aba e fecha sozinho; leva uns 15 segundos)";
  chrome.runtime.sendMessage({ tipo: "testar", url }, (r) => {
    el("teste").textContent = r && r.link ? "DEU CERTO! Seu link: " + r.link
      : "Não consegui: " + ((r && r.erro) || "sem resposta") + "\nTire um print desta janela e mande para o Claude.";
    el("teste").style.whiteSpace = "pre-wrap";
  });
});

mostrar();
