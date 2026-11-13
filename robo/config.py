"""Configurações do robô Drop Certo.

Todas as chaves e senhas vêm de variáveis de ambiente (no GitHub, em
Settings > Secrets and variables > Actions). Nada sensível fica no código.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_FONTES = RAIZ / "assets" / "fonts"
PASTA_SAIDA = RAIZ / "saida"

# Para rodar no seu PC: as chaves podem ficar num arquivo .env na pasta do robô
_ARQ_ENV = RAIZ / ".env"
if _ARQ_ENV.exists():
    for _linha in _ARQ_ENV.read_text(encoding="utf-8").splitlines():
        _linha = _linha.strip()
        if _linha and not _linha.startswith("#") and "=" in _linha:
            _chave, _valor = _linha.split("=", 1)
            os.environ.setdefault(_chave.strip(), _valor.strip().strip('"'))


def _env(nome: str, padrao: str = "") -> str:
    # Variável vazia (como o GitHub envia quando não foi criada) usa o padrão
    return os.environ.get(nome, "").strip() or padrao


def _env_bool(nome: str, padrao: bool) -> bool:
    valor = _env(nome)
    if not valor:
        return padrao
    return valor.lower() in ("1", "true", "sim", "yes", "s")


# --- Telegram -------------------------------------------------------------
TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")            # token do BotFather
ADMIN_CHAT_ID = _env("ADMIN_CHAT_ID")              # seu ID (só você comanda o robô)
CANAL_ID = _env("CANAL_ID")                        # ex.: @certodrop_ofertas
AUTO_POSTAR_CANAL = _env_bool("AUTO_POSTAR_CANAL", True)

# --- Instagram (API oficial com login do Instagram) -----------------------
IG_TOKEN = _env("IG_TOKEN")                        # só na 1ª vez; depois fica no Supabase
MAKE_WEBHOOK_URL = _env("MAKE_WEBHOOK_URL")        # endereço do cenário do Make.com
AUTO_POSTAR_INSTAGRAM = _env_bool("AUTO_POSTAR_INSTAGRAM", True)

# --- TikTok (via Zernio, plano grátis) ------------------------------------
ZERNIO_API_KEY = _env("ZERNIO_API_KEY")            # Zernio → API Keys (começa com sk_)
ZERNIO_TIKTOK_ACCOUNT = _env("ZERNIO_TIKTOK_ACCOUNT")  # opcional: o robô acha sozinho
AUTO_POSTAR_TIKTOK = _env_bool("AUTO_POSTAR_TIKTOK", True)
# Tipo de aviso comercial no TikTok: brand_content = parceria/afiliado (recomendado)
TIKTOK_AVISO_COMERCIAL = _env("TIKTOK_AVISO_COMERCIAL", "brand_content")
# Máximo de vídeos por dia no TikTok (0 = sem limite). Postar demais derruba o alcance.
# Instagram: Reels no feed limitados (o resto vai só no Story, canal e site)
INSTAGRAM_MAX_DIA = int(_env("INSTAGRAM_MAX_DIA", "6") or 6)
INSTAGRAM_SO_PICO = _env_bool("INSTAGRAM_SO_PICO", False)   # espalhado pelo dia (6 por dia não cabem só no pico)
INSTAGRAM_INTERVALO_H = float(_env("INSTAGRAM_INTERVALO_H", "1") or 1)
TIKTOK_MAX_DIA = int(_env("TIKTOK_MAX_DIA", "5"))
TIKTOK_SO_PICO = _env_bool("TIKTOK_SO_PICO", False)  # espalhado pelo dia (5 por dia)
TIKTOK_INTERVALO_H = float(_env("TIKTOK_INTERVALO_H", "1.5") or 1.5)  # horas mínimas entre vídeos no TikTok
# Instagram pelo Zernio (se o Instagram estiver conectado lá; senão usa o Make)
ZERNIO_INSTAGRAM_ACCOUNT = _env("ZERNIO_INSTAGRAM_ACCOUNT")  # opcional
AUTO_STORY_INSTAGRAM = _env_bool("AUTO_STORY_INSTAGRAM", True)  # Story junto com o Reels

# --- Foto limpa: recorta o produto do print que você manda (Gemini) -----
FOTO_LIMPA = _env_bool("FOTO_LIMPA", True)

# --- Shopee: API oficial de afiliados (lê o produto sem precisar de print) --
SHOPEE_APP_ID = _env("SHOPEE_APP_ID")
SHOPEE_APP_SECRET = _env("SHOPEE_APP_SECRET")
TERABYTE_PARCEIRO = _env("TERABYTE_PARCEIRO", "3559600")   # seu código de parceira da Terabyte (?p=)
TERABYTE_TAG = _env("TERABYTE_TAG", "certodrop")
AWIN_TOKEN = _env("AWIN_TOKEN")                       # Awin → API Credentials (Casas Bahia, KaBuM!…)
AWIN_FEED_KEY = _env("AWIN_FEED_KEY")                 # endereço da "Lista de Feed" (Awin → Ferramentas → Crie um Feed)
FILA_AUTO_AWIN = int(_env("FILA_AUTO_AWIN", "3") or 3)   # produtos da Awin na fila automática
PALAVRAS_AWIN = _env("PALAVRAS_AWIN", "ssd,memoria ram,placa de video,processador,monitor gamer,headset gamer,notebook gamer,mouse gamer")

# Palavras dos mais vendidos do Mercado Livre (/ofertas_ml). Vazio = as mesmas da Shopee
PALAVRAS_ML = _env("PALAVRAS_ML", "")

# --- Cliques do canal: links do Telegram passam pelo site (r.html) para contar o clique ---
RASTREAR_CLIQUES = _env_bool("RASTREAR_CLIQUES", True)
SITE_URL = _env("SITE_URL", "https://certodrop.netlify.app")

# --- Vídeo "Top 5" (terça, quinta e domingo às 20h; prévia às 19h) ---
VIDEO_TOP = _env_bool("VIDEO_TOP", True)

# --- Top do dia no canal (21h) ---
TOP_DO_DIA = _env_bool("TOP_DO_DIA", True)

# --- Aviso de queda de preço no canal (ML e Shopee, conferência das 6h) ----
AVISAR_QUEDAS = _env_bool("AVISAR_QUEDAS", True)
QUEDA_MINIMA = float(_env("QUEDA_MINIMA", "10") or 10)

# --- Amazon: sua tag de associado (o robô confere se cada link tem ela) ----
AMAZON_TAG = _env("AMAZON_TAG", "certodrop-20")

# --- Mercado Livre: API oficial (DevCenter) ---------------------------------
ML_CLIENT_ID = _env("ML_CLIENT_ID")
ML_CLIENT_SECRET = _env("ML_CLIENT_SECRET")

# Seus códigos de afiliada do ML (estão em todo link meli.la seu: matt_word e matt_tool).
# Com eles o robô monta o SEU link de afiliada para produtos sugeridos.
ML_MATT_WORD = _env("ML_MATT_WORD", "heafhbgcd94458")
ML_MATT_TOOL = _env("ML_MATT_TOOL", "66102052")

# --- Fila automática: quando a fila acaba, o robô coloca ofertas novas sozinho ---
FILA_AUTOMATICA = _env_bool("FILA_AUTOMATICA", True)
FILA_AUTO_SHOPEE = int(_env("FILA_AUTO_SHOPEE", "3") or 3)
# Nota da oferta (0-100): oferta da fila automática abaixo disso vai só para o site
NOTA_MINIMA = int(_env("NOTA_MINIMA", "45") or 45)
# Links da Shopee marcados por rede (canal/site/bot…) para o relatório de vendas por origem
MARCAR_ORIGEM_SHOPEE = _env_bool("MARCAR_ORIGEM_SHOPEE", True)
# Bot de busca para seguidores ("ssd 1tb até 300" no privado do bot)
BUSCA_PUBLICA = _env_bool("BUSCA_PUBLICA", False)
BUSCAS_POR_HORA = int(_env("BUSCAS_POR_HORA", "5") or 5)        # por pessoa
BUSCAS_POR_DIA = int(_env("BUSCAS_POR_DIA", "150") or 150)       # todas as pessoas juntas
# "Ainda vale!": repostar no canal oferta que teve clique e continua com o mesmo preço
AINDA_VALE = _env_bool("AINDA_VALE", True)
# Ajudante do PC (gera o meli.la de verdade no Edge logado da dona) — ver robo/ajudante.py
# Resposta rápida do modo instantâneo (ver "Resposta rápida" no robo.yml)
RAPIDO = _env_bool("RAPIDO", False)          # rodada leve: só comandos; arte/vídeo pedem a rodada completa
JA_AVISOU = _env_bool("JA_AVISOU", False)    # rodada completa depois da leve: não repete o "⏳ Recebi!"
AJUDANTE = _env_bool("AJUDANTE", True)
# Canais-fonte (canais públicos de ofertas no Telegram lidos pelo robô) — ver robo/canais.py
CANAIS_MAX_DIA = int(_env("CANAIS_MAX_DIA", "30") or 30)      # ofertas por dia vindas dos canais
CANAIS_FILA_MAX = int(_env("CANAIS_FILA_MAX", "20") or 20)    # não pega mais se a fila já tem isso
CANAIS_MINUTOS = int(_env("CANAIS_MINUTOS", "10") or 10)      # de quanto em quanto tempo olha os canais
CANAIS_CUPONS_AUTO = _env_bool("CANAIS_CUPONS_AUTO", True)   # cupom visto em canal-fonte vai direto para o canal
CANAIS_CUPONS_DIA = int(_env("CANAIS_CUPONS_DIA", "8") or 8)  # no máximo esses cupons automáticos por dia
CANAIS_REPETIR_HORAS = float(_env("CANAIS_REPETIR_HORAS", "6") or 6)   # o mesmo produto pode voltar depois dessas horas
CUPONS_LOJAS = _env_bool("CUPONS_LOJAS", True)                # ajudante lê as páginas de cupons (Terabyte e ML) 1x por dia
# Terabyte e Amazon na fila automática: o ajudante faz 1 busca por loja e o robô escolhe as melhores
FILA_AUTO_TERABYTE = int(_env("FILA_AUTO_TERABYTE", "3") or 3)
FILA_AUTO_AMAZON = int(_env("FILA_AUTO_AMAZON", "3") or 3)
PALAVRAS_TERABYTE = _env("PALAVRAS_TERABYTE", "ssd,memoria ram,placa de video,processador,monitor gamer,"
                         "placa mae,fonte,gabinete gamer,water cooler,headset gamer,teclado mecanico,mouse gamer")
PALAVRAS_AMAZON = _env("PALAVRAS_AMAZON", "ssd,memoria ram ddr4,placa de video,processador ryzen,monitor gamer,"
                       "headset gamer,teclado mecanico,mouse gamer,webcam,roteador wifi 6")
FILA_AUTO_ML_AJUDANTE = int(_env("FILA_AUTO_ML_AJUDANTE", "3") or 3)   # ML na fila automática, só via ajudante
ML_NOS_RANKINGS = False   # Top 5 e custo-benefício sem Mercado Livre (lá o robô não tem link com comissão)
FILA_AUTO_ML = 0      # Mercado Livre fora da fila automática (pedido em 09/11/2026); /ofertas_ml continua

# --- Ofertas sugeridas (todo dia às 10h) -------------------------------
SUGERIR_OFERTAS = _env_bool("SUGERIR_OFERTAS", True)
LOJAS_OFERTAS = _env("LOJAS_OFERTAS", "Mercado Livre,Amazon,Shopee")
# Palavras que o robô busca na Shopee (separe por vírgula)
# Peças de PC (prioridade nas sugestões e no comando /ofertas_pc)
PALAVRAS_PC = _env("PALAVRAS_PC", "placa de video rtx,placa de video radeon,placa mae,processador ryzen,"
                   "processador intel core,memoria ram ddr4,memoria ram ddr5,ssd nvme,fonte 650w 80 plus,"
                   "gabinete gamer,water cooler 240mm,cooler para processador,ventoinha rgb 120mm")
PALAVRAS_SHOPEE = _env("PALAVRAS_SHOPEE", "mouse gamer,teclado mecanico,headset gamer,fone bluetooth,"
                       "ssd,smartwatch,carregador turbo,webcam,suporte notebook,hub usb,"
                       + PALAVRAS_PC)

# --- Fila de postagens (horário de Brasília) ------------------------------
POSTAR_DAS = int(_env("POSTAR_DAS", "10"))          # primeiro post do dia
POSTAR_ATE = int(_env("POSTAR_ATE", "23"))         # depois disso, só no dia seguinte
# Modo "hora" (padrão da fila): 1 post a cada 30 min; no pico, a cada 20 min (3 por hora)
HORARIOS_PICO = _env("HORARIOS_PICO", "11:30-13:30,19:00-23:00")
MINUTOS_FORA_PICO = int(_env("MINUTOS_FORA_PICO", "30"))
MINUTOS_NO_PICO = int(_env("MINUTOS_NO_PICO", "20"))

# --- Página de roteiros (kits para criar o vídeo à mão no Gemini) ---
ROTEIROS = _env_bool("ROTEIROS", True)
ROTEIROS_QUANTOS = int(_env("ROTEIROS_QUANTOS", "6") or 6)     # produtos na página
ROTEIROS_HORAS = float(_env("ROTEIROS_HORAS", "3") or 3)       # de quantas em quantas horas atualiza

# --- Cenas de IA no vídeo (PAGO: precisa de cobrança ativada na conta do Google AI Studio) ---
CENAS_IA = _env_bool("CENAS_IA", True)
# Chave SEPARADA (outro projeto do Google, com cobrança): assim os textos do robô continuam na chave grátis
# e só as imagens são cobradas. Sem essa chave, as cenas de IA ficam desligadas.
GEMINI_API_KEY_PAGA = _env("GEMINI_API_KEY_PAGA")
CENAS_IA_MODELO = _env("CENAS_IA_MODELO", "gemini-3.1-flash-lite-image")     # o mais barato
CENAS_IA_DIA = int(_env("CENAS_IA_DIA", "4") or 4)                           # teto de imagens por dia (2 por vídeo)
CENAS_IA_PRECO_USD = float(_env("CENAS_IA_PRECO_USD", "0.0336") or 0.0336)   # só para a estimativa do /cenas_ia

# --- Gemini (nível gratuito do Google AI Studio) -------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-flash-latest")

# --- Supabase (site) ------------------------------------------------------
SUPABASE_URL = _env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _env("SUPABASE_SERVICE_KEY")        # chave service_role (secreta)
SUPABASE_TABELA = _env("SUPABASE_TABELA", "produtos")
SUPABASE_BUCKET = _env("SUPABASE_BUCKET", "produtos")
# Nomes das colunas da sua tabela (ajuste se o seu site usar outros nomes)
COL_NOME = _env("COL_NOME", "nome")
COL_PRECO = _env("COL_PRECO", "preco")
COL_IMAGEM = _env("COL_IMAGEM", "imagem_url")
COL_LINK = _env("COL_LINK", "link")
COL_PRECO_ANTIGO = _env("COL_PRECO_ANTIGO", "preco_anterior")
COL_DESCRICAO = _env("COL_DESCRICAO", "-")  # "-" = a tabela não tem coluna de descrição
if COL_DESCRICAO == "-":
    COL_DESCRICAO = ""

# --- Marca ----------------------------------------------------------------
MARCA = _env("MARCA", "DROP CERTO")
ARROBA = _env("ARROBA", "@certodrop")
COR_FUNDO = _env("COR_FUNDO", "#0B1220")
COR_DESTAQUE = _env("COR_DESTAQUE", "#FFD43B")
COR_TEXTO = _env("COR_TEXTO", "#FFFFFF")

# --- Voz da narração (edge-tts, gratuita) --------------------------------
# Voz principal: Kokoro, roda no próprio robô (sem bloqueio). Opções pt-BR:
# pm_santa (masculina, escolhida), pm_alex (masculina), pf_dora (feminina)
VOZ_KOKORO = _env("VOZ_KOKORO", "pm_santa")
VELOCIDADE_VOZ = float(_env("VELOCIDADE_VOZ", "1.1"))
VARIAR_VOZ = _env_bool("VARIAR_VOZ", True)
MUSICA_FUNDO = _env_bool("MUSICA_FUNDO", True)                 # música da biblioteca (/musica) nos vídeos
VOLUME_MUSICA = float(_env("VOLUME_MUSICA", "0.12") or 0.12)   # 0.12 = bem baixinha por baixo da voz   # cada modelo de vídeo usa uma voz (Santa, Dora, Alex)
PASTA_MODELOS = RAIZ / "modelos"

AVISO_LEGAL = "#publi · Link de afiliado · Preço sujeito a alteração"
