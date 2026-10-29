// Drop Certo — modo instantâneo.
// O Telegram chama esta função a cada mensagem; ela confere a senha e:
//   • mensagem da dona do robô → roda o robô (robo.yml) na hora;
//   • mensagem de outra pessoa no PRIVADO do bot → roda a busca de ofertas (busca.yml),
//     com freio contra abuso (no máx. 1 a cada 15 s por pessoa e 200 por dia no total).
//
// Configuração no Supabase:
//   • "Verify JWT" DESLIGADO (o Telegram não manda login do Supabase)
//   • Segredo da função: GITHUB_TOKEN_ROBO = token do GitHub com "Actions: Read and write"
// A senha do Telegram e o ID da dona ficam na tabela "config" (o robô grava sozinho).

const REPO = "pedrosantanapsn-create/drop-certo-robo";
const WORKFLOW = "robo.yml";
const WORKFLOW_BUSCA = "busca.yml";
const BUSCAS_DIA = 200;
const INTERVALO_PESSOA_MS = 15_000;

function supa(caminho: string, init: RequestInit = {}) {
  const url = Deno.env.get("SUPABASE_URL");
  const chave = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  return fetch(`${url}/rest/v1/${caminho}`, {
    ...init,
    headers: { apikey: chave, Authorization: `Bearer ${chave}`, "Content-Type": "application/json",
               ...(init.headers ?? {}) },
  });
}

// Freio das buscas públicas (guarda só um código embaralhado do chat, nunca o nome)
async function podeBuscar(chat: string): Promise<boolean> {
  const r = await supa("config?chave=eq.busca_freio&select=valor");
  const linhas: { valor: string }[] = r.ok ? await r.json() : [];
  const hoje = new Date().toISOString().slice(0, 10);
  let freio: { dia: string; total: number; ultimo: Record<string, number> } = { dia: hoje, total: 0, ultimo: {} };
  try { if (linhas[0]?.valor) freio = JSON.parse(linhas[0].valor); } catch { /* recomeça */ }
  if (freio.dia !== hoje) freio = { dia: hoje, total: 0, ultimo: {} };
  const dig = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("dropcerto:" + chat));
  const id = Array.from(new Uint8Array(dig)).slice(0, 6).map((b) => b.toString(16).padStart(2, "0")).join("");
  const agora = Date.now();
  if (freio.total >= BUSCAS_DIA || agora - (freio.ultimo[id] ?? 0) < INTERVALO_PESSOA_MS) return false;
  freio.total += 1;
  freio.ultimo[id] = agora;
  await supa("config", {
    method: "POST",
    headers: { Prefer: "resolution=merge-duplicates" },
    body: JSON.stringify({ chave: "busca_freio", valor: JSON.stringify(freio) }),
  });
  return true;
}

async function lerConfig(): Promise<Record<string, string>> {
  const url = Deno.env.get("SUPABASE_URL");
  const chave = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const r = await fetch(
    `${url}/rest/v1/config?chave=in.(telegram_webhook_secret,admin_chat_id)&select=chave,valor`,
    { headers: { apikey: chave!, Authorization: `Bearer ${chave}` } },
  );
  const linhas: { chave: string; valor: string }[] = r.ok ? await r.json() : [];
  return Object.fromEntries(linhas.map((l) => [l.chave, l.valor]));
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("Drop Certo: ok");

  const cfg = await lerConfig();
  const senha = req.headers.get("x-telegram-bot-api-secret-token") ?? "";
  if (!cfg.telegram_webhook_secret || senha !== cfg.telegram_webhook_secret) {
    return new Response("acesso negado", { status: 401 });
  }

  const update = await req.json().catch(() => null);
  const chat = update?.message?.chat?.id;
  let workflow = WORKFLOW;
  if (!update?.message) return new Response("ignorado");
  if (String(chat) !== String(cfg.admin_chat_id)) {
    // Outras pessoas: só texto no privado do bot vira busca; o resto é ignorado
    const texto = String(update.message.text ?? "");
    if (update.message.chat?.type !== "private" || !texto || texto.length > 200) {
      return new Response("ignorado");
    }
    if (!(await podeBuscar(String(chat)))) return new Response("freio");
    workflow = WORKFLOW_BUSCA;
  }
  // O repositório é público: a mensagem de seguidores NÃO vai no pedido ao GitHub (apareceria
  // nos registros). Ela fica guardada no Supabase e o robô busca por um código e apaga em seguida.
  let entrada = JSON.stringify(update);
  if (workflow === WORKFLOW_BUSCA) {
    const ref = "busca_msg_" + crypto.randomUUID();
    const minima = { update_id: update.update_id,
                     message: { chat: { id: chat, type: "private" }, text: String(update.message.text ?? "") } };
    await supa("config", { method: "POST", body: JSON.stringify({ chave: ref, valor: JSON.stringify(minima) }) });
    entrada = JSON.stringify({ ref });
  }

  const token = Deno.env.get("GITHUB_TOKEN_ROBO");
  if (!token) return new Response("falta GITHUB_TOKEN_ROBO", { status: 500 });

  const gh = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "drop-certo-robo",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { update: entrada } }),
    },
  );
  // Se o GitHub recusar, devolve erro: o Telegram tenta de novo depois (só para a dona)
  if (!gh.ok && workflow === WORKFLOW_BUSCA) return new Response("busca recusada");
  if (!gh.ok) return new Response(`GitHub ${gh.status}: ${await gh.text()}`, { status: 502 });
  return new Response("ok");
});
