// Drop Certo — modo instantâneo.
// O Telegram chama esta função a cada mensagem; ela confere a senha e se a
// mensagem é da dona do robô, e manda o GitHub rodar o robô na hora.
//
// Configuração no Supabase:
//   • "Verify JWT" DESLIGADO (o Telegram não manda login do Supabase)
//   • Segredo da função: GITHUB_TOKEN_ROBO = token do GitHub com "Actions: Read and write"
// A senha do Telegram e o ID da dona ficam na tabela "config" (o robô grava sozinho).

const REPO = "pedrosantanapsn-create/drop-certo-robo";
const WORKFLOW = "robo.yml";

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
  // Mensagens de outras pessoas: responde 200 (o Telegram não reenvia) e ignora
  if (!update?.message || String(chat) !== String(cfg.admin_chat_id)) {
    return new Response("ignorado");
  }

  const token = Deno.env.get("GITHUB_TOKEN_ROBO");
  if (!token) return new Response("falta GITHUB_TOKEN_ROBO", { status: 500 });

  const gh = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "drop-certo-robo",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { update: JSON.stringify(update) } }),
    },
  );
  // Se o GitHub recusar, devolve erro: o Telegram tenta de novo depois
  if (!gh.ok) return new Response(`GitHub ${gh.status}: ${await gh.text()}`, { status: 502 });
  return new Response("ok");
});
