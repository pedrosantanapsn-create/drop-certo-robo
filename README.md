# Robô Drop Certo

Automação de ofertas de afiliado (tecnologia, informática e peças de PC) para o **Drop Certo**:
canal do Telegram [@DropCerto22](https://t.me/DropCerto22), Instagram **@certodrop**, TikTok **@certo.drop**
e o site **certodrop.netlify.app**.

Você manda um link (ou deixa a fila automática escolher) e o robô faz o resto: lê o produto, monta arte e
vídeo com narração, escreve a legenda com #publi e publica em todos os canais, nos melhores horários.

**Custo: R$ 0** — GitHub Actions, Telegram, Supabase (plano grátis), Netlify, Gemini (nível gratuito),
voz Kokoro (roda no próprio robô), APIs oficiais da Shopee e do Mercado Livre, Zernio para Instagram/TikTok.

---

## 1. Como funciona

```
Telegram (você) ──► Supabase (função telegram-robo, modo instantâneo) ──► GitHub Actions (robo.yml)
                                                                            │
          ┌────────────────────────┬──────────────────────┬─────────────────┼──────────────────┐
          ▼                        ▼                      ▼                 ▼                  ▼
   Canal do Telegram         Site (Supabase +       Instagram Reels    TikTok (Zernio)    Relatórios e
   (link rastreado r.html)   Netlify)               + Story (Zernio)                      alertas no bot
```

- **robo.yml** roda a cada 10 min (cron-job.org) e na hora em que você manda mensagem (modo instantâneo).
  Um passo rápido confere se há algo a fazer (mensagem, fila, relatório, conferência, quadro, top do dia…)
  antes de instalar tudo.
- **site.yml** publica a pasta `site/` na Netlify sempre que ela muda.
- Estado (fila, histórico, tokens, horários) fica na tabela `config` do Supabase.

## 2. Lojas

| Loja | Leitura do produto | Link de afiliado | Sugestões |
|---|---|---|---|
| **Shopee** | API oficial de afiliados (sem print) | gerado pela API (`generateShortLink`) | `/shopee`, 10h, fila automática |
| **Mercado Livre** | API oficial (produtos de catálogo) | meli.la seu ou link com `matt_word`/`matt_tool` | `/ofertas_ml`, fila automática |
| **Amazon** | print (Gemini lê nome e preço e recorta o produto) | tag `certodrop-20` colocada sozinha | `/ofertas_amazon` (Promobit) |
| **Awin** (Casas Bahia, KaBuM!…) | feed de produtos da loja (nome, preço, foto) ou página/print | gerado pela API da Awin (Link Builder) ou já vem no feed; só lojas que aceitaram você | `/awin_ofertas`, `/casasbahia`, `/awin_cupons`, fila automática (3) |
| **TikTok Shop** | nome e foto da página; preço por print ou `preco:` | o link que você compartilha | — |

## 3. O que roda sozinho

| Quando | O quê |
|---|---|
| 10h–23h | Fila: 1 post a cada 30 min; no pico (11h30–13h30 e 19h–23h) a cada 20 min |
| Cada post | Canal no formato compacto (foto do produto, nome, preço, cupom, link limpo); arte + vídeo (4 modelos em rodízio) + legenda → Reels (máx. 6/dia, 1 h de intervalo) e TikTok (máx. 5/dia, 1h30 de intervalo) |
| Fila acabou | Fila automática: 5 Shopee + 5 Mercado Livre, **só marcas conhecidas**, prioridade para peças de PC, para o que está no menor preço em 30 dias e para o que o público mais clica |
| Cada oferta | **Nota de 0 a 100** (desconto real pelo histórico, marca, nota e vendas na loja, comissão, peça de PC, cupom). Da fila automática, nota abaixo de 45 vai só para o site; no pico sai primeiro a de maior nota |
| Cada oferta | **Desconto falso**: se o "de R$" nunca apareceu no histórico de 30 dias, o post sai sem "de R$" e sem "% OFF" (CDC art. 37) |
| 18h | **"🔁 Ainda vale!"**: reposta no canal 1 oferta que teve clique e continua com o mesmo preço (Shopee/ML, conferido pela API) |
| Toda busca/conferência | Histórico de preços próprio (60 dias): "📉 Menor preço em 30 dias" e alerta de **possível erro de preço** (≥ 50% abaixo da mediana) no bot com `/add B1` |
| Horário marcado | Cupons agendados (`hora: 00:00`) saem no canal sozinhos |
| 6h | Conferência de preços (APIs/página), ofertas esgotadas saem do site (2 conferências seguidas), checagem de saúde das conexões |
| a partir das 10h | Avisos de "baixou o preço" no canal (≥ 10%, ML e Shopee) |
| 10h | Sugestões do dia (Promobit + Shopee) |
| Ter/Qui/Dom 19h → 20h | Vídeo "Top 5", alternando "custo-benefício" e "mais bem avaliados" (prévia às 19h, `/cancelar_top`; publica às 20h no Reels, Story, TikTok e canal) |
| 21h | Top 5 do dia no canal |
| Segunda 9h | Relatório da semana (posts, cliques do canal e do site) |
| Qualquer erro | Alerta imediato no bot (no máx. 1 por problema a cada 6 h) |

## 4. Comandos do bot

| Comando | Para quê |
|---|---|
| link (ou vários, um por linha) | posta na hora (1 link) ou põe na fila (vários) |
| print + link na legenda | Amazon / TikTok Shop: lê preço e recorta o produto |
| `preco:` `de:` `nome:` `cupom:` `alerta: bug` | linhas embaixo do link para completar/corrigir (`alerta: bug` = post "⚠️ POSSÍVEL ERRO DE PREÇO") |
| `/fila` `/agora` `/limpar` `/intervalo` | fila de posts |
| `/ofertas` `/shopee` `/ofertas_ml` `/ofertas_amazon` `/ofertas_pc` | sugestões (com bloco de links para copiar) |
| `/add S1 M3` · `/add todos` | põe na fila itens da última sugestão |
| `/custo fone com dongle até 300` | vídeo Top 5 de custo-benefício (ficha técnica + preço + nota, IA grátis) |
| `/video_top fone bluetooth até 100` · `/cancelar_top` | vídeo "Top 5" na hora · cancela o das 20h |
| áudio + `/musica` · `/musicas` · `/tirar_musica N` | biblioteca de músicas de fundo (Pixabay, sem Content ID) |
| `/cupom CODIGO descrição` + `loja:` `validade:` passos `1.` `2.` `hora: 00:00` | post de cupom com passo a passo, na hora ou agendado · `/cupons` · `/cancelar_cupom CODIGO` |
| `/regras` | publica e fixa as regras do canal |

**De onde vêm as vendas:** links da Shopee saem marcados por rede (`canal`, `site`, `bot`, `aindavale`);
o relatório de segunda mostra os pedidos e a comissão da Shopee por origem (API de conversões).
No site, o clique registra se a pessoa veio do Instagram, TikTok ou Telegram (link da bio com
`?origem=insta` / `?origem=tiktok`, ou automático pelo endereço de origem) — só o nome da rede.
| `/site link` + `preco:` | só no site, sem postar de novo |
| `/relatorio [dias]` `/conferir` | relatório e conferência na hora |
| `/ml` `/instagram` `/tiktok` `/voz` `/instantaneo` | conferir ligações |

**Quadro de ofertas:** `certodrop.netlify.app/quadro.html` (login do admin) — imagem em cima, link embaixo,
"+" para mais quadros; o robô importa para a fila em até 10 min.

## 5. Configuração

**Secrets (GitHub → Settings → Secrets and variables → Actions):**
`TELEGRAM_TOKEN`, `ADMIN_CHAT_ID`, `CANAL_ID`, `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`ZERNIO_API_KEY`, `AWIN_TOKEN`, `AWIN_FEED_KEY`, `SHOPEE_APP_ID`, `SHOPEE_APP_SECRET`, `ML_CLIENT_ID`, `ML_CLIENT_SECRET`,
`NETLIFY_AUTH_TOKEN`, `MAKE_WEBHOOK_URL` (reserva do Instagram, opcional).

**Variáveis opcionais (aba Variables)** — todas têm padrão:

| Variável | Padrão | Para quê |
|---|---|---|
| `INSTAGRAM_MAX_DIA` / `INSTAGRAM_SO_PICO` / `INSTAGRAM_INTERVALO_H` | 6 / false / 1 | limite de Reels |
| `TIKTOK_MAX_DIA` / `TIKTOK_SO_PICO` / `TIKTOK_INTERVALO_H` | 5 / false / 1.5 | limite do TikTok |
| `HORARIOS_PICO` | 11:30-13:30,19:00-23:00 | horários de pico |
| `FILA_AUTOMATICA` / `FILA_AUTO_SHOPEE` / `FILA_AUTO_ML` | true / 5 / 5 | fila automática |
| `PALAVRAS_PC` / `PALAVRAS_SHOPEE` / `PALAVRAS_ML` | peças de PC + periféricos | o que buscar |
| `QUEDA_MINIMA` / `AVISAR_QUEDAS` | 10 / true | aviso de queda de preço |
| `NOTA_MINIMA` | 45 | nota mínima para oferta da fila automática ir às redes |
| `MARCAR_ORIGEM_SHOPEE` | true | links da Shopee marcados por rede |
| `AINDA_VALE` | true | repost "Ainda vale!" das 18h |
| `TOP_DO_DIA` / `RASTREAR_CLIQUES` | true / true | top das 21h e cliques do canal |
| `AMAZON_TAG` | certodrop-20 | sua tag da Amazon |
| `ML_MATT_WORD` / `ML_MATT_TOOL` | seus códigos | link de afiliada do ML |
| `VOZ_KOKORO` / `VELOCIDADE_VOZ` / `VARIAR_VOZ` | pm_santa / 1.1 / true | narração (com VARIAR_VOZ cada modelo usa uma voz: Santa, Dora, Alex) |
| `VIDEO_TOP` | true | vídeos Top 5 de terça, quinta e domingo |
| `MUSICA_FUNDO` / `VOLUME_MUSICA` | true / 0.12 | música da biblioteca por baixo da narração |

**Supabase:** tabelas `produtos` (site), `config` (estado do robô), `cliques` (só inserção pública);
bucket `produtos` (fotos, quadro); função `telegram-robo` (modo instantâneo, Verify JWT desligado,
segredo `GITHUB_TOKEN_ROBO`).

## 6. Regras que o robô segue (legislação brasileira)

- Post do canal: "(ANÚNCIO) #publi · link de afiliado" e "Preço visto em dd/mm hh:mm, pode mudar".
- "📉 Menor preço em 30 dias" só com 7 dias ou mais de histórico próprio (nunca inventado).

- Todo post leva **#publi** e o aviso de link de afiliado (CONAR, CDC art. 36); na Amazon também
  "Como Associado da Amazon, eu ganho com compras qualificadas.".
- Preço com data/hora; site esconde o preço da Amazon após 24 h; "de R$" só quando é verdade e é apagado
  quando deixa de ser; ofertas esgotadas saem do site (CDC art. 37).
- Cupom só entra quando você escreve, com regras e validade.
- Nenhuma foto é "inventada" por IA: o recorte usa a foto real do anúncio.
- Cliques são contados sem nenhum dado do visitante (LGPD).
- Chaves só nos Secrets do GitHub / Supabase — nunca no site nem no código.

## 7. Arquivos

`main.py` (comandos e fluxo do post) · `robo/` (um módulo por assunto: `fila`, `sugestoes`, `reabastecer`,
`shopee`, `mercadolivre`, `amazon`, `verificador`, `quedas`, `top`, `alertas`, `rastreio`, `relatorio`,
`arte`, `video`, `recorte`, `legenda`, `instagram`, `tiktok`, `zernio`, `quadro`…) · `site/` (vitrine,
admin, quadro, `r.html` dos cliques, `ml.html` da autorização) · `supabase/functions/telegram-robo`.
