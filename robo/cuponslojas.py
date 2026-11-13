"""Cupons das lojas, lidos pelo ajudante (a extensão no navegador da dona).

Uma vez por dia (9h) o robô pede ao ajudante para abrir as páginas de cupons da Terabyte e do
Mercado Livre — a do ML só aparece para quem está logada. O ajudante devolve o que está escrito
na página e o robô manda para a dona a lista dos cupons NOVOS.

O robô NÃO divulga esses cupons sozinho: cupom tem regra (valor mínimo, produtos, validade) e
anunciar condição errada é oferta enganosa (CDC art. 37). A dona confere e divulga com /cupom.

Comando: /cupons_lojas (pede agora e mostra todos).  Desligar o diário: variável CUPONS_LOJAS=false.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from . import ajudante, config, fila, supabase

PAGINAS = {
    "terabyte": {"nome": "Terabyte", "url": "https://www.terabyteshop.com.br/cupons"},
    "ml": {"nome": "Mercado Livre", "url": "https://www.mercadolivre.com.br/cupons"},
}
CHAVE_DIA = "cupons_lojas_dia"
CHAVE_VISTOS = "cupons_lojas_vistos"
HORA = 9
RE_VALOR = re.compile(r"\d{1,2}\s?%|R\$\s?\d", re.I)
RE_SINAL = re.compile(r"\boff\b|cupom|cupon|desconto", re.I)
RE_LIXO = re.compile(r"^(entrar|cadastr|minha conta|carrinho|buscar|menu|ver mais|ver todos|aplicar|ativar|"
                     r"copiar|copiado|resgatar|usar cupom|ver produtos|ver regras|saiba mais|termos.*)$", re.I)


def pedir(manual: bool = False) -> int:
    """Cria os pedidos de leitura das páginas de cupons. Devolve quantos pedidos novos."""
    agora = datetime.now(fila.FUSO)
    carimbo = agora.strftime("%Y%m%d%H%M" if manual else "%Y%m%d")
    feitos = 0
    for qual, pagina in PAGINAS.items():
        if ajudante.pedir(f"cupons:{qual}:{carimbo}", pagina["url"], {"manual": manual}, loja=f"cupons_{qual}"):
            feitos += 1
    return feitos


def pedir_se_for_hora() -> int:
    """1x por dia, depois das 9h, se o ajudante deu sinal nos últimos dias."""
    if not (config.CUPONS_LOJAS and ajudante.ativo()):
        return 0
    agora = datetime.now(fila.FUSO)
    hoje = agora.strftime("%Y-%m-%d")
    if agora.hour < HORA or (supabase.ler_config(CHAVE_DIA) or {}).get("valor") == hoje:
        return 0
    supabase.gravar_config(CHAVE_DIA, hoje)
    if not ajudante.usado_recentemente(3):
        return 0
    return pedir()


def _limpo(bloco: str) -> str:
    linhas = [l.strip() for l in str(bloco or "").splitlines()]
    linhas = [l for l in linhas if l and not RE_LIXO.match(l)]
    return " · ".join(dict.fromkeys(linhas))[:260]


def _do_texto(texto: str) -> list[str]:
    """Plano B (a página não tinha "cartões" reconhecíveis): cada linha com valor de desconto
    vira um cupom, junto com as 3 linhas seguintes (regras, código, validade)."""
    linhas = [l.strip() for l in str(texto or "").splitlines() if l.strip()]
    blocos, pular = [], 0
    for n, linha in enumerate(linhas):
        if pular:
            pular -= 1
            continue
        if RE_VALOR.search(linha) and RE_SINAL.search(" ".join(linhas[n:n + 3])) and len(linha) < 160:
            blocos.append("\n".join(linhas[n:n + 4]))
            pular = 3
    return blocos


def extrair(dados: dict) -> list[str]:
    """Cupons da página, um por linha, sem repetir."""
    brutos = [str(i) for i in (dados.get("itens") or [])] or _do_texto(str(dados.get("texto") or ""))
    cupons = []
    for bloco in brutos:
        linha = _limpo(bloco)
        if len(linha) >= 8 and RE_VALOR.search(linha) and linha not in cupons:
            cupons.append(linha)
    return cupons[:25]


def _marca(qual: str, linha: str) -> str:
    return hashlib.md5(f"{qual}:{re.sub(r'[^a-z0-9%$]', '', linha.lower())}".encode()).hexdigest()[:12]


def mensagem(qual: str, dados: dict) -> str | None:
    """Texto para a dona. No pedido diário mostra só os cupons novos (None = nada novo)."""
    pagina = PAGINAS.get(qual) or {"nome": qual, "url": ""}
    manual = bool(dados.get("manual"))
    cupons = extrair(dados)
    if not cupons:
        return (f"🎟️ {pagina['nome']}: abri a página de cupons e não achei nenhum cupom agora.\n{pagina['url']}"
                if manual else None)
    try:
        vistos = json.loads((supabase.ler_config(CHAVE_VISTOS) or {}).get("valor") or "[]")
    except ValueError:
        vistos = []
    novos = [c for c in cupons if _marca(qual, c) not in vistos]
    supabase.gravar_config(CHAVE_VISTOS, json.dumps((vistos + [_marca(qual, c) for c in novos])[-500:]))
    mostrar = cupons if manual else novos
    if not mostrar:
        return None
    linhas = [f"🎟️ Cupons {'na' if qual == 'terabyte' else 'no'} {pagina['nome']} — "
              + ("todos os que estão na página" if manual else f"{len(mostrar)} novo(s) hoje"), ""]
    linhas += [f"{n}. {c}" for n, c in enumerate(mostrar[:15], 1)]
    if len(mostrar) > 15:
        linhas.append(f"… e mais {len(mostrar) - 15}")
    linhas += ["", f"🔎 Confira as regras na página: {pagina['url']}",
               "📣 Para divulgar no canal: /cupom CODIGO descrição  (mande /cupom sozinho para ver o modelo)",
               "ℹ️ Eu não divulgo sozinho: cupom tem valor mínimo, produtos e validade — confira antes."]
    if qual == "ml":
        linhas.append("ℹ️ No Mercado Livre os cupons mudam de conta para conta: estes são os da SUA conta.")
    return "\n".join(linhas)
