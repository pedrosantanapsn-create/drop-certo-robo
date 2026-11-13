"""Posts copiados de outros canais de ofertas → ofertas com o SEU link.

Você copia (ou encaminha) um post de outro canal, por exemplo:

    Fonte Asrock Pro 750w 80 Plus Bronze
    Resgate cupom no anuncio!
    💵 R$ 311
    🎟️ Cupom: MELIPROMO3111 + Siga a loja e resgate os cupons
    https://meli.la/1jkmt89
    (ANUNCIO)
    🏆 Amazon prime (30 dias grátis)
    https://amzn.to/xxxx

e o robô transforma em:

    https://meli.la/1jkmt89
    nome: Fonte Asrock Pro 750w 80 Plus Bronze
    preco: 311
    cupom: MELIPROMO3111 + Siga a loja e resgate os cupons

O link do outro canal é trocado pelo SEU na hora de postar (Amazon, Mercado Livre,
Shopee, KaBuM/Awin e Terabyte). Links de "Amazon Prime grátis", grupos e redes sociais
são ignorados. Vários posts colados juntos viram vários itens na fila.
"""
from __future__ import annotations

import re

from .fila import RE_LINK

RE_ANUNCIO = re.compile(r"^\W*\(?\s*an[uú]ncio\s*\)?\W*$", re.I)
RE_PRECO = re.compile(r"R\$\s*([\d.]+(?:,\d{1,2})?)", re.I)
RE_CUPOM = re.compile(r"cupo[mn]\s*:?\s*([A-Z0-9][A-Z0-9_-]{3,})(.*)", re.I)
RE_IGNORAR_LINK = re.compile(r"t\.me/|chat\.whatsapp|whatsapp\.com|instagram\.com|tiktok\.com/@|"
                             r"youtube\.com|youtu\.be|amazon\.com\.br/prime|/prime\b", re.I)
RE_LINHA_IGNORAR = re.compile(r"prime|grupo|canal|whatsapp|telegram|siga a gente|link do produto|"
                              r"compre aqui|resgate|^\W*$", re.I)
SINAIS = ("(anuncio)", "(anúncio)", "link do produto", "no pix", "cupom:", "🎟", "💵", "👇")


def e_post_copiado(texto: str) -> bool:
    """Parece um post de outro canal de ofertas (e não uma mensagem no formato do robô)?"""
    t = (texto or "").lower()
    if not RE_LINK.search(t) or re.search(r"^\s*(nome|preco|preço|de|cupom)\s*:", t, re.M):
        return False
    return sum(s in t for s in SINAIS) >= 1 and len([l for l in t.splitlines() if l.strip()]) >= 3


def _blocos(texto: str) -> list[list[str]]:
    blocos, atual = [], []
    for linha in (texto or "").splitlines():
        if RE_ANUNCIO.match(linha.strip()):
            blocos.append(atual)
            atual = []
        else:
            atual.append(linha.strip())
    blocos.append(atual)
    return [b for b in blocos if any(RE_LINK.search(l) for l in b)]


def separar(texto: str) -> list[str]:
    """Cada post copiado vira uma oferta no formato do robô (link + nome/preço/cupom)."""
    ofertas = []
    for bloco in _blocos(texto):
        link, nome, preco, cupom, pix, pular = "", "", "", "", False, False
        for linha in bloco:
            baixa = linha.lower()
            achados = [l.rstrip(").,;!?") for l in RE_LINK.findall(linha)]
            if "prime" in baixa or "grupo" in baixa or "whatsapp" in baixa:
                pular = True             # o próximo link é de propaganda (Prime, grupo…), não do produto
                continue
            if achados:
                if pular:
                    pular = False
                    continue
                for l in achados:
                    if not link and not RE_IGNORAR_LINK.search(l):
                        link = l
                continue
            m = RE_CUPOM.search(linha)
            if m and not cupom:
                cupom = (m.group(1).upper() + " " + m.group(2).strip(" -–:")).strip()
                continue
            # "10x de R$ 19,99" é parcela, não o preço
            m = RE_PRECO.search(re.sub(r"\d+\s*x\s*(de\s*)?R\$\s*[\d.,]+", " ", linha, flags=re.I))
            if m and not preco:
                preco = m.group(1)
                pix = pix or "pix" in baixa
                continue
            if not nome and len(linha) > 12 and not RE_LINHA_IGNORAR.search(linha):
                nome = re.sub(r"^[^\wÀ-ú]+", "", linha).strip()
        if not link:
            continue
        partes = [link]
        if nome:
            partes.append(f"nome: {nome[:150]}")
        if preco:
            partes.append(f"preco: {preco}")
        if cupom:
            partes.append(f"cupom: {cupom[:80]}")
        if pix:
            partes.append("obs: preço no Pix")
        ofertas.append("\n".join(partes))
    return ofertas
