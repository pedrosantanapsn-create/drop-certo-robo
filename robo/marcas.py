"""Marcas que o público gamer/tech reconhece — a fila automática só pega essas,
e as sugestões dão prioridade a elas (oferta "certeira" = marca conhecida + preço bom)."""
from __future__ import annotations

import re

MARCAS = [
    # processador / placa de vídeo / placa-mãe
    "amd", "ryzen", "intel", "nvidia", "geforce", "radeon", "asus", "rog", "tuf gaming", "gigabyte", "aorus", "msi",
    "asrock", "galax", "pny", "zotac", "sapphire", "powercolor", "palit", "inno3d", "biostar",
    # memória / armazenamento
    "kingston", "fury", "hyperx", "corsair", "crucial", "samsung", "western digital", "wd ", "seagate", "sandisk",
    "xpg", "adata", "lexar", "netac", "patriot", "teamgroup", "t-force", "kingspec", "husky",
    # fonte / gabinete / refrigeração
    "rise mode", "cooler master", "deepcool", "lian li", "nzxt", "thermaltake", "be quiet", "pcyes", "redragon",
    "aigo", "darkflash", "montech", "gamdias", "kalkan", "superframe", "mancer", "pichau", "evga", "seasonic",
    "c3tech", "bluecase", "k-mex", "tgt", "duex",
    # periféricos / áudio
    "logitech", "razer", "steelseries", "attack shark", "vgn", "vxe", "machenike", "aula", "royal kludge", "rk ",
    "keychron", "akko", "havit", "fallen", "multilaser warrior", "warrior", "edifier", "jbl", "sony", "philips",
    "anker", "soundcore", "baseus", "ugreen", "qcy", "haylou", "xiaomi", "redmi", "realme", "lenovo", "acer",
    "dell", "hp ", "lg ", "aoc", "agon", "tcl", "benq", "viewsonic", "philco", "positivo", "gamesir", "8bitdo",
    "flydigi", "dualsense", "playstation", "xbox", "nintendo", "apple", "iphone", "airpods", "motorola", "huawei",
    "amazfit", "mibro", "tp-link", "mercusys", "intelbras", "elgato", "fifine", "maono", "hyperx", "astro",
    "turtle beach", "oex", "goldentec", "knup",
]
_RE = re.compile(r"(?:^|[^a-z0-9])(" + "|".join(re.escape(m.strip()) for m in sorted(set(MARCAS), key=len, reverse=True))
                 + r")(?:[^a-z0-9]|$)", re.I)


# "Carregador para iPhone", "Suporte compatível com Nvidia": a marca é do OUTRO produto
_RE_COMPAT = re.compile(r"\b(para|pra|p/|compat[ií]vel|compat|serve|tipo|estilo|similar|igual|modelo)\b", re.I)


def marca(nome: str) -> str:
    """Marca conhecida do PRÓPRIO produto, ou '' se for genérico.

    Só vale a marca que aparece antes de "para / compatível com…" e nas primeiras 8 palavras.
    """
    texto = f" {nome or ''} "
    corte = _RE_COMPAT.search(texto)
    if corte:
        texto = texto[:corte.start()] + " "
    texto = " " + " ".join(texto.split()[:8]) + " "
    m = _RE.search(texto)
    return m.group(1).strip() if m else ""


def conhecida(nome: str) -> bool:
    return bool(marca(nome))
