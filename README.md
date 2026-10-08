# Robô Drop Certo — Etapa 1

Você manda o seu link de afiliado (`meli.la/...`) para o seu bot no Telegram. O robô devolve, em poucos minutos:

| Entrega | Onde |
|---|---|
| 🖼️ Arte do feed (1080×1350) com foto, preço, desconto e aviso de publicidade | No seu Telegram e no canal |
| 🎬 Vídeo vertical de 12–15 s (1080×1920) com narração, para Reels, TikTok e Shorts | No seu Telegram |
| 📋 Legenda pronta com #publi e hashtags | No seu Telegram |
| 📢 Post automático no canal público com o link clicável | Canal do Telegram |
| 🌐 Produto cadastrado no site (Supabase) | Seu site na Netlify |

**Custo: R$ 0.** Usa apenas serviços gratuitos (GitHub Actions, API do Telegram, Gemini no nível gratuito, edge-tts e FFmpeg).

> **Por que o robô não gera o link de afiliado sozinho?** O Mercado Livre não tem uma API oficial para afiliados. As ferramentas que geram o link sozinhas usam os cookies da sua conta, o que pode violar os termos e levar à suspensão. Aqui você gera o link no app do ML (5 segundos), e o robô faz todo o resto sem acessar a sua conta.

---

## 1. O que você vai precisar

- [x] Bot do Telegram criado no BotFather (você já tem)
- [x] Chave do Gemini no Google AI Studio (você já tem)
- [x] Projeto Supabase do site (você já tem)
- [ ] Um **canal público** no Telegram
- [ ] Uma conta no **GitHub**, que é gratuita

---

## 2. Passo a passo

### Passo 1 — Canal público no Telegram

1. No Telegram, toque em ✏️ e depois em **Novo canal**.
2. Escolha **Canal público** e defina o link, por exemplo `t.me/certodrop_ofertas`.
   O programa de afiliados só aceita canais públicos. Grupos fechados não valem.
3. Abra o canal, vá em **Administradores → Adicionar administrador** e adicione o seu bot.
   Deixe ativada a permissão **Publicar mensagens**.
4. Cadastre o canal no painel do Programa de Afiliados do Mercado Livre como canal de divulgação.

### Passo 2 — Repositório no GitHub

1. Entre em <https://github.com> e clique em **New repository**.
2. Use o nome `drop-certo-robo` e marque **Public**.
   - Em repositório **público**, os minutos do GitHub Actions são **ilimitados e gratuitos**.
   - As suas chaves **não ficam visíveis**: elas vão em "Secrets", que ninguém consegue ler.
   - Se preferir **Private**, o limite é de 2.000 minutos por mês. Nesse caso troque `*/10` por `*/30` no arquivo `.github/workflows/robo.yml`.
3. Clique em **uploading an existing file** e arraste **todo o conteúdo** desta pasta, incluindo a pasta `.github`.
4. Clique em **Commit changes**.

### Passo 3 — Cadastrar as chaves (Secrets)

No repositório, abra **Settings → Secrets and variables → Actions → New repository secret** e crie um segredo para cada item:

| Nome do segredo | O que colocar | Onde encontrar |
|---|---|---|
| `TELEGRAM_TOKEN` | Token do bot | BotFather → `/mybots` → API Token |
| `CANAL_ID` | `@nome_do_seu_canal` | Link do canal |
| `GEMINI_API_KEY` | Chave do Gemini | <https://aistudio.google.com/apikey> |
| `SUPABASE_URL` | `https://xxxx.supabase.co` | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_KEY` | Chave **service_role** | Supabase → Project Settings → API |
| `ADMIN_CHAT_ID` | Seu ID do Telegram | Veja o Passo 4 |

> ⚠️ A chave `service_role` dá acesso total ao banco. Coloque-a **somente** em Secrets e nunca no código do site.

### Passo 4 — Primeiro teste e seu ID

1. No GitHub, vá em **Actions** e clique em **I understand… enable them**, se aparecer.
2. No Telegram, mande `/start` para o seu bot.
3. Em **Actions → Robô Drop Certo**, clique em **Run workflow**. Isso roda na hora, sem esperar os 10 minutos.
4. O bot responde: **"Seu ID do Telegram é: 123456789"**.
5. Crie o segredo `ADMIN_CHAT_ID` com esse número. A partir daí **só você** consegue usar o robô.

### Passo 5 — Conferir as colunas do site

1. Mande `/colunas` para o bot e rode o workflow de novo.
2. O bot lista os nomes das colunas da sua tabela de produtos.
3. Se forem diferentes do padrão (`nome`, `preco`, `imagem_url`, `link`, `descricao`), vá em **Settings → Secrets and variables → Actions → aba Variables** e crie as variáveis com os nomes certos. Por exemplo, `COL_IMAGEM` com o valor `foto`.
4. Se a tabela ou o bucket tiverem outro nome, crie também `SUPABASE_TABELA` e `SUPABASE_BUCKET`.

---

## 3. Como usar no dia a dia

1. No app do Mercado Livre, ache a oferta e toque em **Compartilhar** para gerar o link de afiliado `meli.la/...`.
2. Cole o link no chat do seu bot e envie.
3. Em até ~10 minutos chegam a arte, o vídeo e a legenda. O post do canal e o cadastro no site já ficam feitos.
4. Publique o vídeo no Instagram, TikTok e YouTube Shorts colando a legenda. Leva cerca de 1 minuto.

### Formatos aceitos

Só o link:
```
meli.la/2VjtBGz
```

Corrigindo ou completando dados (uma informação por linha):
```
meli.la/2VjtBGz
nome: Mouse Gamer Sem Fio RGB
preco: 89,90
de: 149,90
obs: bom para quem joga FPS
```

**Com foto:** mande uma foto do produto e escreva o link na legenda. O robô usa a sua foto.

### Comandos

| Comando | Para quê |
|---|---|
| `/ajuda` | Mostra os formatos aceitos |
| `/id` | Mostra o seu ID do Telegram |
| `/colunas` | Lista as colunas da tabela do site |

---

## 4. Opcional: rodar no seu PC (resposta na hora)

No GitHub o robô confere as mensagens a cada ~10 minutos. Com o PC ligado, ele responde em segundos.

1. Instale o Python: <https://www.python.org/downloads/>. Marque **"Add python.exe to PATH"** na instalação.
2. Instale o FFmpeg. No Prompt de Comando, rode `winget install Gyan.FFmpeg`.
   A arte usa a fonte Inter (licença livre OFL), que o GitHub instala sozinho. No PC, se ela não estiver instalada, o robô usa Arial.
3. Copie `.env.exemplo` para `.env` e preencha as chaves.
4. Dê dois cliques em **`ligar_robo_no_pc.bat`**.

> Não deixe o PC e o GitHub ligados ao mesmo tempo. Os dois disputariam as mesmas mensagens. Enquanto usar o PC, desative o workflow em **Actions → Robô Drop Certo → ⋯ → Disable workflow**.

Para conferir o visual sem internet, rode `python main.py --teste`. A arte e o vídeo de exemplo ficam em `saida/teste/`.

---

## 5. Estrutura do projeto

```
drop-certo-robo/
├── main.py                  # Recebe as mensagens e coordena tudo
├── robo/
│   ├── config.py            # Chaves, cores e nomes de colunas
│   ├── produto.py           # Lê nome, preço e fotos do anúncio
│   ├── legenda.py           # Textos com Gemini (com modelo de reserva)
│   ├── arte.py              # Arte do feed e quadros do vídeo
│   ├── video.py             # Vídeo com FFmpeg + narração
│   ├── telegram.py          # API do Telegram
│   └── supabase.py          # Cadastro no site
├── .github/workflows/robo.yml  # Agendamento gratuito no GitHub
├── .env.exemplo             # Modelo de chaves para rodar no PC
└── ligar_robo_no_pc.bat     # Liga o robô no Windows
```

### Mudar as cores da marca

Crie as variáveis `COR_FUNDO`, `COR_DESTAQUE` e `COR_TEXTO` com cores em hexadecimal, por exemplo `#0B1220`. Também dá para mudar `ARROBA` e `MARCA`.

---

## 6. Limitações e cuidados

| Situação | O que acontece | O que fazer |
|---|---|---|
| O ML bloqueia a leitura do anúncio | Os servidores do GitHub às vezes são vistos como robô | O bot avisa e pede `nome:` e `preco:`. Mande junto uma foto do produto |
| O agendamento atrasa | O GitHub pode atrasar execuções agendadas em horários de pico | Use **Run workflow** ou rode no PC |
| 60 dias sem alterações no repositório | O GitHub desativa o agendamento de repositórios públicos | Reative em **Actions** ou faça qualquer commit |
| Limite diário do Gemini | O robô usa um modelo de texto pronto | Nada. O post sai do mesmo jeito |
| Narração indisponível | O vídeo sai sem voz | Coloque um áudio em alta ao publicar no app |
| Preço mudou depois do post | O ML altera preços com frequência | A legenda já traz "Preço sujeito a alteração" |

### Regras que o robô já respeita

- **#publi e "Link de afiliado"** em toda arte, vídeo e legenda. O CDC (art. 36) exige que a publicidade seja identificável, e o Guia de Publicidade por Influenciadores Digitais do CONAR orienta sinalizar o conteúdo comercial.
- A IA recebe instruções para **não inventar** especificações, estoque ou urgência falsa, para evitar publicidade enganosa (CDC, art. 37).
- O robô não acessa a sua conta do Mercado Livre e não compra tráfego.
- Só você comanda o robô. Mensagens de outras pessoas são ignoradas.

---

## 7. Próximas etapas

- **Etapa 2:** postagem automática no Instagram pela API oficial da Meta.
- **Etapa 3:** busca de ofertas de informática para você só aprovar e gerar o link.
