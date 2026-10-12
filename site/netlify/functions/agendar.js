// Função serverless (Netlify Functions, grátis) que faz a ponte entre o
// admin.html e o Postiz. A chave da API do Postiz fica AQUI (variável de
// ambiente do Netlify), nunca no navegador.
//
// Variáveis de ambiente necessárias (Netlify → Site configuration → Environment variables):
//   SUPABASE_URL            ex.: https://xxxx.supabase.co
//   SUPABASE_ANON_KEY       chave publicável (sb_publishable_...) — valida o login do admin
//   SUPABASE_SERVICE_KEY    chave secreta (sb_secret_...) — grava o histórico de agendamentos
//   POSTIZ_URL              ex.: https://postiz.seudominio.duckdns.org   (sem barra no final)
//   POSTIZ_API_KEY          Postiz → Settings → Public API → copiar
//   POSTIZ_INTEGRATION_INSTAGRAM  (opcional) id da conta no Postiz; se vazio, detecta pelo provider
//   POSTIZ_INTEGRATION_TIKTOK     (opcional) idem

export default async (req) => {
  if (req.method !== 'POST') return new Response(JSON.stringify({ erro: 'Método não permitido' }), { status: 405 });

  const env = process.env;
  for (const k of ['SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_KEY','POSTIZ_URL','POSTIZ_API_KEY']) {
    if (!env[k]) return resp(500, { erro: `Variável de ambiente ${k} não configurada no Netlify.` });
  }

  // 1) Confere se quem chamou está logado no admin (token do Supabase)
  const token = (req.headers.get('authorization') || '').replace('Bearer ', '');
  if (!token) return resp(401, { erro: 'Não autenticado.' });
  const u = await fetch(`${env.SUPABASE_URL}/auth/v1/user`, { headers: { apikey: env.SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` } });
  if (!u.ok) return resp(401, { erro: 'Sessão inválida. Faça login novamente.' });

  let body;
  try { body = await req.json(); } catch { return resp(400, { erro: 'JSON inválido.' }); }
  const { texto, midia_url, plataformas = [], data, produto_id = null } = body;
  if (!texto || !midia_url || !plataformas.length || !data) return resp(400, { erro: 'Campos obrigatórios: texto, midia_url, plataformas, data.' });
  if (new Date(data) < new Date(Date.now() + 5 * 60000)) return resp(400, { erro: 'A data precisa ser pelo menos 5 minutos no futuro.' });

  const POSTIZ = env.POSTIZ_URL.replace(/\/$/, '');
  // Com o docker-compose oficial, o backend responde em /api
  const API = `${POSTIZ}/api/public/v1`;
  const H = { Authorization: env.POSTIZ_API_KEY };

  try {
    // 2) Descobre os ids das contas conectadas no Postiz
    const ir = await fetch(`${API}/integrations`, { headers: H });
    if (!ir.ok) throw new Error(`Postiz não respondeu (${ir.status}). O servidor está no ar?`);
    const integracoes = await ir.json();
    const achar = (prov, fixo) => fixo || (integracoes.find(i => (i.providerIdentifier || i.identifier || '').toLowerCase().includes(prov) && !i.disabled) || {}).id;
    const ids = {
      instagram: achar('instagram', env.POSTIZ_INTEGRATION_INSTAGRAM),
      tiktok: achar('tiktok', env.POSTIZ_INTEGRATION_TIKTOK),
    };
    for (const p of plataformas) if (!ids[p]) throw new Error(`Conta ${p} não está conectada no Postiz.`);

    // 3) Sobe a mídia para o Postiz (ele exige mídia hospedada nele)
    const m = await fetch(midia_url);
    if (!m.ok) throw new Error('Não consegui baixar a mídia informada.');
    const blob = await m.blob();
    const nomeArq = midia_url.split('/').pop().split('?')[0] || 'midia.jpg';
    const fd = new FormData();
    fd.append('file', blob, nomeArq);
    const up = await fetch(`${API}/upload`, { method: 'POST', headers: H, body: fd });
    if (!up.ok) throw new Error(`Falha no upload para o Postiz (${up.status}): ${await up.text()}`);
    const midia = await up.json(); // { id, path }

    // 4) Monta um post por rede, no formato da API pública do Postiz
    const settings = {
      instagram: { __type: 'instagram', post_type: 'post', collaborators: [] },
      tiktok: {
        __type: 'tiktok', privacy_level: 'PUBLIC_TO_EVERYONE', duet: false, stitch: false, comment: true,
        brand_content_toggle: true, brand_organic_toggle: false, content_posting_method: 'DIRECT_POST', autoAddMusic: 'no',
      },
    };
    const payload = {
      type: 'schedule',
      date: new Date(data).toISOString(),
      shortLink: false,
      tags: [],
      posts: plataformas.map(p => ({
        integration: { id: ids[p] },
        value: [{ content: texto, image: [{ id: midia.id, path: midia.path }] }],
        settings: settings[p],
      })),
    };
    const pr = await fetch(`${API}/posts`, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const ptxt = await pr.text();
    if (!pr.ok) throw new Error(`Postiz recusou o agendamento (${pr.status}): ${ptxt}`);
    let pres; try { pres = JSON.parse(ptxt); } catch { pres = { raw: ptxt }; }

    // 5) Grava o histórico no Supabase
    await gravar(env, { produto_id, texto, midia_url, plataformas, data_publicacao: data, status: 'agendado', postiz_id: JSON.stringify(pres).slice(0, 200) });
    return resp(200, { ok: true, postiz: pres });
  } catch (err) {
    await gravar(env, { produto_id, texto, midia_url, plataformas, data_publicacao: data, status: 'erro', erro: err.message.slice(0, 500) }).catch(() => {});
    return resp(502, { erro: err.message });
  }
};

function resp(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

async function gravar(env, registro) {
  const r = await fetch(`${env.SUPABASE_URL}/rest/v1/agendamentos`, {
    method: 'POST',
    // Chave secreta (sb_secret_...) vai SÓ no header apikey — não é JWT, não usar Bearer.
    headers: { apikey: env.SUPABASE_SERVICE_KEY, 'Content-Type': 'application/json', Prefer: 'return=minimal' },
    body: JSON.stringify(registro),
  });
  if (!r.ok) console.error('Falha ao gravar agendamento:', await r.text());
}

export const config = { path: '/.netlify/functions/agendar' };
