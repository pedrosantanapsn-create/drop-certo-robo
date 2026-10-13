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
# Instagram pelo Zernio (se o Instagram estiver conectado lá; senão usa o Make)
ZERNIO_INSTAGRAM_ACCOUNT = _env("ZERNIO_INSTAGRAM_ACCOUNT")  # opcional
AUTO_STORY_INSTAGRAM = _env_bool("AUTO_STORY_INSTAGRAM", True)  # Story junto com o Reels

# --- Foto limpa: recorta o produto do print que você manda (Gemini) -----
FOTO_LIMPA = _env_bool("FOTO_LIMPA", True)

# --- Shopee: API oficial de afiliados (lê o produto sem precisar de print) --
SHOPEE_APP_ID = _env("SHOPEE_APP_ID")
SHOPEE_APP_SECRET = _env("SHOPEE_APP_SECRET")

# --- Ofertas sugeridas (todo dia às 10h) -------------------------------
SUGERIR_OFERTAS = _env_bool("SUGERIR_OFERTAS", True)
LOJAS_OFERTAS = _env("LOJAS_OFERTAS", "Mercado Livre,Amazon,Shopee")

# --- Fila de postagens (horário de Brasília) ------------------------------
POSTAR_DAS = int(_env("POSTAR_DAS", "8"))          # primeiro post do dia
POSTAR_ATE = int(_env("POSTAR_ATE", "22"))         # depois disso, só no dia seguinte

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
VOZ = _env("VOZ", "pt-BR-FranciscaNeural")         # Microsoft (reserva)
# Voz principal: Kokoro, roda no próprio robô (sem bloqueio). Opções pt-BR:
# pm_santa (masculina, escolhida), pm_alex (masculina), pf_dora (feminina)
VOZ_KOKORO = _env("VOZ_KOKORO", "pm_santa")
VELOCIDADE_VOZ = float(_env("VELOCIDADE_VOZ", "1.1"))
PASTA_MODELOS = RAIZ / "modelos"

AVISO_LEGAL = "#publi · Link de afiliado · Preço sujeito a alteração"
