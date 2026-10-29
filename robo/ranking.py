"""Vídeos "Top 5" (ranking) — terça, quinta e domingo às 20h.

• 19h: o robô escolhe a categoria do dia (gira e não repete por 4 semanas), busca
  os produtos nas APIs (Shopee: nota e vendas; Mercado Livre: mais vendidos) e
  manda uma PRÉVIA para você. /cancelar_top cancela.
• 20h: monta o vídeo (capa → #5 … #1 → final), com narração e um dos modelos de
  cor/voz, e publica no Reels, Story, TikTok e no canal (com os 5 links rastreados).
  Esse vídeo usa a vaga "reservada" do dia no Reels e no TikTok (os posts comuns
  desse dia ficam com 1 vaga a menos), então não passa dos limites.
• /video_top fone bluetooth até 100 → monta e publica um ranking na hora.

Linguagem: "mais bem avaliados" / "mais vendidos", com o critério dito no vídeo —
o robô não testa os produtos, então não chama de "melhores" (CDC art. 37; CONAR).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import requests

from . import (arte, config, gemini, instagram, marcas, mercadolivre, rastreio, relatorio, shopee,
               sugestoes, supabase, telegram, tiktok, video)
from .fila import FUSO
from .produto import formatar_preco

CHAVE_ESTADO = "ranking_estado"
CHAVE_PROXIMO = "ranking_proximo"
CHAVE_HISTORICO = "ranking_historico"
HORA_PREVIA, HORA_POST = 19, 20
DIAS = {1: "perifericos", 3: "pc", 6: "audio"}       # terça, quinta, domingo
NOMES_DIA = {1: "terça", 3: "quinta", 6: "domingo"}
SEMANAS_SEM_REPETIR = 4

# (palavra de busca, nome no título, teto de preço ou None)
CATEGORIAS = {
    "perifericos": [("mouse gamer", "mouses gamer", 150), ("teclado mecanico", "teclados mecânicos", 250),
                    ("headset gamer", "headsets gamer", 200), ("webcam full hd", "webcams", 200),
                    ("mousepad gamer", "mousepads gamer", 80), ("controle bluetooth", "controles sem fio", 250)],
    "pc": [("ssd nvme", "SSDs NVMe", 400), ("memoria ram ddr4", "memórias RAM DDR4", 300),
           ("water cooler 240mm", "water coolers", 500), ("fonte 650w 80 plus", "fontes 650W", 500),
           ("gabinete gamer", "gabinetes gamer", 400), ("cooler para processador", "coolers para processador", 200)],
    "audio": [("fone bluetooth", "fones bluetooth", 100), ("smartwatch", "smartwatches", 250),
              ("caixa de som bluetooth", "caixas de som bluetooth", 200), ("carregador turbo", "carregadores turbo", 80),
              ("power bank", "power banks", 150), ("fone gamer bluetooth", "fones gamer sem fio", 200)],
}


# ---------------------------------------------------------------------------
# Estado (Supabase)
# ---------------------------------------------------------------------------
def _ler(chave: str, padrao):
    try:
        return json.loads((supabase.ler_config(chave) or {}).get("valor") or json.dumps(padrao))
    except ValueError:
        return padrao


def _hoje() -> str:
    return datetime.now(FUSO).strftime("%Y-%m-%d")


def estado_hoje() -> dict:
    estado = _ler(CHAVE_ESTADO, {})
    return estado if estado.get("data") == _hoje() else {}


def reservado_hoje() -> bool:
    """Hoje é dia de Top 5 e ele ainda não saiu: os posts comuns deixam 1 vaga livre no Reels e no TikTok."""
    if not (config.VIDEO_TOP and supabase.ativo()):
        return False
    if datetime.now(FUSO).weekday() not in DIAS:
        return False
    return estado_hoje().get("fase") not in ("postado", "cancelado", "sem_produtos")


def _proximo_dia_util(agora: datetime) -> datetime:
    for i in range(0, 8):
        dia = agora + timedelta(days=i)
        alvo = dia.replace(hour=HORA_PREVIA, minute=0, second=0, microsecond=0)
        if dia.weekday() in DIAS and alvo > agora:
            return alvo
    return agora + timedelta(days=1)


# ---------------------------------------------------------------------------
# Escolha da categoria e dos produtos
# ---------------------------------------------------------------------------
def escolher_categoria(grupo: str) -> tuple[str, str, int | None]:
    historico = _ler(CHAVE_HISTORICO, [])
    recentes = {h.get("palavra") for h in historico[-(SEMANAS_SEM_REPETIR * len(DIAS)):]}
    opcoes = CATEGORIAS[grupo]
    for palavra, titulo, teto in opcoes:
        if palavra not in recentes:
            return palavra, titulo, teto
    usadas = [h.get("palavra") for h in historico]
    return min(opcoes, key=lambda o: max((i for i, u in enumerate(usadas) if u == o[0]), default=-1))


def _parecidos(a: str, b: str) -> bool:
    pa = set(re.findall(r"[a-z0-9]{3,}", a.lower()))
    pb = set(re.findall(r"[a-z0-9]{3,}", b.lower()))
    return bool(pa and pb) and len(pa & pb) / min(len(pa), len(pb)) > 0.6


def buscar_produtos(palavra: str, teto: float | None, quantos: int = 5) -> list[dict]:
    """[{nome, preco, nota, vendas, link, imagem, loja}] — ordenados do melhor para o 5º."""
    candidatos: list[dict] = []
    if shopee.ativo():
        vistos = set()
        for ordem in (shopee.ORDEM_MAIS_VENDIDOS, shopee.ORDEM_MAIOR_COMISSAO):
            try:
                nos = shopee.buscar(palavra, ordem, 50)
            except Exception as erro:  # noqa: BLE001
                print(f"::warning::Top 5 Shopee: {str(erro)[:120]}")
                continue
            for n in nos:
                if n.get("itemId") in vistos:
                    continue
                vistos.add(n.get("itemId"))
                preco = sugestoes._num(n.get("priceMin"), None)
                nota = sugestoes._num(n.get("ratingStar"))
                vendas = int(sugestoes._num(n.get("sales")))
                nome = str(n.get("productName") or "")
                if not preco or (teto and preco > teto) or nota < 4.5 or vendas < 50:
                    continue
                if sugestoes.RE_NAO_PC.search(nome):
                    continue
                candidatos.append({"nome": nome, "preco": preco, "nota": nota, "vendas": vendas,
                                   "link": n.get("productLink") or n.get("offerLink"), "imagem": n.get("imageUrl"),
                                   "loja": "Shopee", "_nota": nota * 20 + math.log10(vendas + 1) * 8})
    candidatos.sort(key=lambda c: -c["_nota"])
    escolhidos: list[dict] = []
    for c in candidatos:
        if any(_parecidos(c["nome"], e["nome"]) for e in escolhidos):
            continue
        escolhidos.append(c)
        if len(escolhidos) >= quantos:
            break
    # Link de afiliada da Shopee só para os escolhidos (poupa chamadas)
    for c in escolhidos:
        try:
            c["link"] = shopee.link_afiliado(str(c["link"]), "dropcerto_top5")
        except Exception:  # noqa: BLE001
            pass
    if len(escolhidos) < quantos and mercadolivre.ativo():
        try:
            for n in sugestoes.buscar_ml([palavra], quantas=quantos * 2):
                if teto and n["preco"] > teto:
                    continue
                if any(_parecidos(n["nome"], e["nome"]) for e in escolhidos):
                    continue
                escolhidos.append({"nome": n["nome"], "preco": n["preco"], "nota": None, "vendas": None,
                                   "link": n["link"], "imagem": None, "id_ml": n["id"], "loja": "Mercado Livre",
                                   "_nota": 0})
                if len(escolhidos) >= quantos:
                    break
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Top 5 ML: {str(erro)[:120]}")
    return escolhidos[:quantos]


# ---------------------------------------------------------------------------
# Modo CUSTO-BENEFÍCIO (grátis): ficha técnica + preço + nota, avaliado pelo Gemini
# ---------------------------------------------------------------------------
SINONIMOS = {
    "dongle": r"2[.,]4\s*g|dongle|receptor|wireless usb|usb wireless|lightspeed",
    "bluetooth": r"bluetooth|\bbt\s*5",
    "rgb": r"\brgb\b",
    "microfone": r"microfone|\bmic\b",
    "mecanico": r"mec[aâ]nico|switch",
    "sem fio": r"sem fio|wireless|bluetooth|2[.,]4\s*g",
    "anc": r"\banc\b|cancelamento (ativo )?de ru[ií]do",
}


def separar_pedido(texto: str) -> tuple[str, float | None, list[str]]:
    """'fone com dongle até 300' -> ('fone', 300, ['dongle'])"""
    m = re.search(r"(?:at[eé]|<=?)\s*r?\$?\s*(\d+)", texto, re.I)
    teto = float(m.group(1)) if m else None
    resto = re.sub(r"(?:at[eé]|<=?)\s*r?\$?\s*\d+", "", texto, flags=re.I).strip()
    requisitos = []
    if " com " in f" {resto} ":
        palavra, _, extras = f" {resto} ".partition(" com ")
        requisitos = [r.strip() for r in re.split(r"\s+e\s+|,", extras) if r.strip()]
        resto = palavra.strip()
    return resto, teto, requisitos


TIPOS = {
    "fone": r"fone|headset|headphone|auricular|earbud|tws",
    "fones": r"fone|headset|headphone|auricular|earbud|tws",
    "headset": r"headset|fone|headphone",
    "mouse": r"mouse", "teclado": r"teclado|keyboard", "ssd": r"\bssd\b",
    "memoria": r"mem[oó]ria|ram\b", "monitor": r"monitor", "webcam": r"webcam|c[aâ]mera",
    "controle": r"controle|gamepad|joystick", "caixa": r"caixa de som|speaker",
}


RE_ACESSORIO = re.compile(r"\badaptador|\bcabo\b|\bcapa\b|\bcase\b|suporte|almofada|espuma|dissipador|"
                          r"protetor|pel[ií]cula|\bkit \d+ adaptador|transmissor|reposi[cç][aã]o|"
                          r"case|gaveta|cooler para ssd|heatsink|receptor avulso", re.I)


def _e_do_tipo(nome: str, palavra: str) -> bool:
    """O anúncio é do produto pedido? (evita 'adaptador dongle' numa busca de fone)"""
    nome = (nome or "").lower()
    inicio = " ".join(nome.split()[:6])          # o "tipo" do anúncio vem nas primeiras palavras
    if RE_ACESSORIO.search(inicio) and not RE_ACESSORIO.search(palavra):
        return False
    for tok in re.findall(r"[a-zà-ú0-9]{3,}", palavra.lower()):
        padrao = TIPOS.get(tok, re.escape(tok).replace("e", "[eé]") if tok.isalpha() else re.escape(tok))
        if not re.search(padrao, nome, re.I):
            return False
    return True


def _atende(texto: str, requisitos: list[str]) -> bool:
    texto = (texto or "").lower()
    for req in requisitos:
        padrao = SINONIMOS.get(req.lower().replace("ê", "e"), re.escape(req.lower()))
        if not re.search(padrao, texto, re.I):
            return False
    return True


def _ficha_ml(produto_id: str) -> str:
    try:
        p = mercadolivre._get(f"/products/{produto_id}")
    except Exception:  # noqa: BLE001
        return ""
    attrs = [f"{a.get('name')}: {a.get('value_name')}" for a in (p.get("attributes") or [])
             if a.get("value_name") and len(str(a.get("value_name"))) < 40][:18]
    return "; ".join(attrs)


RE_CAPACIDADE = re.compile(r"\b\d+\s?(?:gb|tb)\b", re.I)


def _varias_versoes(nome: str) -> bool:
    """Anúncio com várias capacidades ("120GB 240GB 1TB"): o preço mostrado é o da menor — engana."""
    return len({m.group(0).lower().replace(" ", "") for m in RE_CAPACIDADE.finditer(nome or "")}) >= 3


def buscar_custo(palavra: str, teto: float | None, requisitos: list[str], quantos: int = 5,
                 sub_id: str = "dropcerto_custo") -> list[dict]:
    """Candidatos que cumprem o pedido; o Gemini escolhe os 5 de melhor custo-benefício."""
    busca = " ".join([palavra, *requisitos]).strip()
    candidatos: list[dict] = []
    if shopee.ativo():
        vistos = set()
        curto = " ".join(palavra.split()[:2])
        extras = []
        for req in requisitos:                       # ex.: dongle -> "fone 2.4g", "headset 2.4g"
            if req.lower() == "dongle":
                extras += [f"{palavra} 2.4g", f"{palavra} 2.4ghz receptor usb"]
                if re.search(r"fone|headset", palavra, re.I):
                    extras += ["headset gamer sem fio 2.4g", "headset wireless 2.4ghz", "fone gamer sem fio 2.4g"]
            elif req.lower() == "sem fio":
                extras.append(f"{palavra} wireless")
        for termo in dict.fromkeys([t for t in [busca, *extras, palavra, curto, f"{palavra} original"] if t]):
            for ordem in (shopee.ORDEM_MAIS_VENDIDOS, shopee.ORDEM_MAIOR_COMISSAO):
                try:
                    nos = shopee.buscar(termo, ordem, 50)
                except Exception:  # noqa: BLE001
                    continue
                for n in nos:
                    nome = str(n.get("productName") or "")
                    preco = sugestoes._num(n.get("priceMin"), None)
                    nota = sugestoes._num(n.get("ratingStar"))
                    vendas = int(sugestoes._num(n.get("sales")))
                    if n.get("itemId") in vistos or not preco or (teto and preco > teto):
                        continue
                    vistos.add(n.get("itemId"))
                    if (nota < 4.3 or vendas < 15 or sugestoes.RE_NAO_PC.search(nome) or _varias_versoes(nome)
                            or not _atende(nome, requisitos) or not _e_do_tipo(nome, palavra)):
                        continue
                    candidatos.append({"nome": nome, "preco": preco, "nota": nota, "vendas": vendas, "ficha": nome,
                                       "link": n.get("productLink") or n.get("offerLink"),
                                       "imagem": n.get("imageUrl"), "loja": "Shopee"})
    if mercadolivre.ativo():
        try:
            dominio = (mercadolivre._get("/sites/MLB/domain_discovery/search", q=busca, limit=1) or [{}])[0]
            ranking_ml = (mercadolivre._get(f"/highlights/MLB/category/{dominio['category_id']}").get("content")
                          if dominio.get("category_id") else []) or []
            for pos in ranking_ml[:20]:
                if pos.get("type") != "PRODUCT":
                    continue
                pid = pos["id"]
                try:
                    prod = mercadolivre._get(f"/products/{pid}")
                    vend = (mercadolivre._get(f"/products/{pid}/items").get("results") or [{}])[0]
                except Exception:  # noqa: BLE001
                    continue
                nome, preco = prod.get("name", ""), vend.get("price")
                if not preco or (teto and preco > teto) or not _e_do_tipo(nome, palavra):
                    continue
                ficha = "; ".join(f"{a.get('name')}: {a.get('value_name')}" for a in (prod.get("attributes") or [])
                                  if a.get("value_name") and len(str(a.get("value_name"))) < 40)[:600]
                if not _atende(nome + " " + ficha, requisitos):
                    continue
                candidatos.append({"nome": nome, "preco": preco, "nota": None, "vendas": None,
                                   "ficha": f"{pos.get('position')}º mais vendido da categoria; {ficha}",
                                   "link": mercadolivre.link_afiliado(pid), "imagem": None,
                                   "id_ml": pid, "loja": "Mercado Livre"})
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Custo ML: {str(erro)[:120]}")
    # tira repetidos e limita a 16 para a IA comparar
    unicos: list[dict] = []
    for c in sorted(candidatos, key=lambda c: -((c["nota"] or 4.5) * 20 + math.log10((c["vendas"] or 100) + 1) * 8
                                                + (12 if marcas.conhecida(c["nome"]) else 0))):
        if not any(_parecidos(c["nome"], u["nome"]) for u in unicos):
            unicos.append(c)
        if len(unicos) >= 16:
            break
    if len(unicos) < 3:
        return []
    escolhidos = _avaliar_custo(palavra, requisitos, teto, unicos, quantos)
    for c in escolhidos:
        if c["loja"] == "Shopee":
            try:
                c["link"] = shopee.link_afiliado(str(c["link"]), sub_id)
            except Exception:  # noqa: BLE001
                pass
    return escolhidos


def _avaliar_custo(palavra, requisitos, teto, cands: list[dict], quantos: int) -> list[dict]:
    """Gemini compara ficha × preço × nota. Sem Gemini: fórmula simples (nota e vendas por real)."""
    lista = [{"i": i, "nome": c["nome"][:140], "preco": c["preco"], "nota": c["nota"], "vendas": c["vendas"],
              "ficha": (c["ficha"] or "")[:500]} for i, c in enumerate(cands)]
    prompt = (
        f"Você é um analista de custo-benefício de tecnologia. Produto procurado: {palavra}"
        + (f" com {', '.join(requisitos)}" if requisitos else "") + (f", até R$ {int(teto)}" if teto else "")
        + ".\nCompare os candidatos abaixo usando SOMENTE os dados informados (nome, ficha, preço, nota e vendas). "
        "Custo-benefício = o que o produto entrega (recursos, bateria, conexões, capacidade, potência) pelo preço, "
        "com nota boa como garantia. Não invente especificações que não estão nos dados. "
        f"DESCARTE o que não for de fato um(a) {palavra} (acessórios, peças, adaptadores) e o que não cumprir o pedido.\n"
        f"Escolha até {quantos} em ordem (1 = melhor) e para cada um escreva um motivo de no máximo "
        "10 palavras citando RECURSOS concretos da ficha (ex.: 'dongle e Bluetooth, 26h de bateria'); "
        "não repita preço nem nota no motivo (já aparecem no vídeo).\n"
        'Responda só JSON: [{"i": 0, "motivo": "..."}]\n' + json.dumps(lista, ensure_ascii=False))
    try:
        dados, _ = gemini.chamar([{"text": prompt}], temperatura=0.2)
        resposta = json.loads(re.sub(r"^```(?:json)?|```$", "", gemini.texto(dados).strip(), flags=re.M))
        escolhidos = []
        for r in resposta:
            i = int(r.get("i", -1))
            if 0 <= i < len(cands) and cands[i] not in escolhidos:
                cands[i]["motivo"] = str(r.get("motivo") or "")[:80]
                escolhidos.append(cands[i])
        return escolhidos[:quantos]          # a IA descartou o resto (acessórios, fora do pedido)
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Custo-benefício (Gemini): {str(erro)[:150]}")
    def nota(c):
        return ((c["nota"] or 4.5) * 20 + math.log10((c["vendas"] or 100) + 1) * 8) / max(c["preco"], 1) ** 0.35
    return sorted(cands, key=nota, reverse=True)[:quantos]


def _nomes_curtos(nomes: list[str]) -> list[str]:
    """Nomes de até 6 palavras para a tela e a narração (Gemini; se falhar, corta)."""
    reserva = [" ".join(re.sub(r"[|,(\[].*$", "", n).split()[:6]) or n[:40] for n in nomes]
    if not config.GEMINI_API_KEY:
        return reserva
    prompt = ("Resuma cada nome de produto em no máximo 6 palavras, mantendo marca e modelo, sem inventar nada. "
              "Responda só uma lista JSON de textos, na mesma ordem.\n" + json.dumps(nomes, ensure_ascii=False))
    try:
        dados, _ = gemini.chamar([{"text": prompt}], temperatura=0.2, json_saida=True)
        lista = json.loads(re.sub(r"^```(?:json)?|```$", "", gemini.texto(dados).strip(), flags=re.M))
        if isinstance(lista, list) and len(lista) == len(nomes):
            return [str(x)[:60] or r for x, r in zip(lista, reserva)]
    except Exception:  # noqa: BLE001
        pass
    return reserva


def _preco_falado(valor: float) -> str:
    reais, centavos = int(valor), round((valor - int(valor)) * 100)
    return f"{reais} reais" + (f" e {centavos}" if centavos else "")


# ---------------------------------------------------------------------------
# Vídeo e publicação
# ---------------------------------------------------------------------------
CRITERIOS = {"avaliados": "pela nota e pelas vendas de quem comprou",
             "custo": "pela ficha técnica, preço e avaliação dos compradores"}


def _titulo(titulo: str, teto: float | None, modo: str = "avaliados") -> str:
    base = f"custo-benefício: {titulo}" if modo == "custo" else f"{titulo} mais bem avaliados"
    return base + (f" até R$ {int(teto)}" if teto else "")


def publicar(palavra: str, titulo: str, teto: float | None, itens: list[dict], enviar,
             reservado: bool, modo: str = "avaliados") -> list[str]:
    """Monta o vídeo e publica. Devolve as linhas de status."""
    status: list[str] = []
    pasta = Path(tempfile.mkdtemp(prefix="top5_"))
    try:
        try:
            numero = int(str((supabase.ler_config("modelo_video") or {}).get("valor") or 0))
            modelo = video.usar_modelo(numero)
            supabase.gravar_config("modelo_video", str(numero + 1))
            status.append(f"• Modelo: {modelo['nome']} · voz {config.VOZ_KOKORO}")
        except Exception:  # noqa: BLE001
            pass
        curtos = _nomes_curtos([i["nome"] for i in itens])
        fotos: list[Path | None] = []
        for k, item in enumerate(itens):
            foto = None
            url = item.get("imagem")
            if not url and item.get("id_ml"):
                try:
                    imgs = (mercadolivre._get(f"/products/{item['id_ml']}").get("pictures") or [])
                    url = imgs[0].get("url") if imgs else None
                except Exception:  # noqa: BLE001
                    url = None
            if url:
                try:
                    r = requests.get(url, timeout=30)
                    r.raise_for_status()
                    foto = pasta / f"p{k}.jpg"
                    foto.write_bytes(r.content)
                except Exception:  # noqa: BLE001
                    foto = None
            fotos.append(foto)

        titulo_video = _titulo(titulo, teto, modo)
        criterio = CRITERIOS.get(modo, CRITERIOS["avaliados"])
        capa = arte.cena_ranking_capa(titulo_video, f"Ranking {criterio}", pasta / "capa.png")
        cenas = [(capa, 1.3)]
        if modo == "custo":
            falas = [f"Os {len(itens)} {titulo} com melhor custo-benefício"
                     + (f" até {int(teto)} reais" if teto else "") + f", {criterio}."]
        else:
            falas = [f"Os {len(itens)} {titulo} mais bem avaliados" + (f" até {int(teto)} reais" if teto else "")
                     + f", {criterio}."]
        for pos in range(len(itens), 0, -1):
            item, nome = itens[pos - 1], curtos[pos - 1]
            cenas.append((arte.cena_ranking_item(pos, nome, item["preco"], item.get("nota"), item.get("vendas"),
                                                 item["loja"], fotos[pos - 1], pasta / f"item{pos}.png",
                                                 motivo=item.get("motivo", "")), 1.15 if item.get("motivo") else 1.0))
            fala = f"Número {pos}: {nome}, por {_preco_falado(item['preco'])}"
            if item.get("motivo"):
                fala += f". {item['motivo']}"
            elif item.get("nota") and pos == 1:     # nota falada só no 1º (vídeo mais curto)
                fala += f", nota {str(round(item['nota'], 1)).replace('.', ',')}"
            falas.append(fala + ".")
        cenas.append((arte.cena_ranking_fim(pasta / "fim.png"), 0.8))
        falas.append("Qual você levaria? Links no canal e na bio.")
        caminho, com_voz = video.renderizar(cenas, " ".join(falas), pasta, "top5.mp4")
        status.append("• Vídeo: pronto" + (" com narração" if com_voz else " (sem narração)"))

        linhas_lista = [f"{p}. {curtos[p - 1]} — {formatar_preco(itens[p - 1]['preco'])}"
                        + (f" ({itens[p - 1]['motivo']})" if itens[p - 1].get("motivo") else "")
                        for p in range(1, len(itens) + 1)]
        hashtags = "#top5 #achadinhos #tecnologia #custobeneficio #oferta"
        legenda_redes = "\n".join([f"🏆 Top {len(itens)} {titulo_video}", f"(ranking {criterio})", "",
                                   *linhas_lista, "", f"🛒 Links no canal do Telegram e na bio · {config.ARROBA}",
                                   "", config.AVISO_LEGAL, hashtags])

        # Canal do Telegram: capa + lista com os 5 links rastreados
        if config.CANAL_ID:
            try:
                partes = [f"🏆 <b>TOP {len(itens)} {escape(titulo_video.upper())}</b>",
                          f"<i>Ranking {escape(criterio)}</i>", ""]
                for p in range(1, len(itens) + 1):
                    it = itens[p - 1]
                    extra = f" · ★ {it['nota']:.1f}".replace(".", ",") if it.get("nota") else ""
                    if it.get("motivo"):
                        extra += f"\n   <i>{escape(it['motivo'])}</i>"
                    url = rastreio.link(str(it["link"]), None, curtos[p - 1])
                    partes.append(f"{p}. {escape(curtos[p - 1])} — {formatar_preco(it['preco'])}{extra}  "
                                  f"<a href=\"{escape(url)}\">ver ➜</a>")
                partes += ["", "Preços vistos agora — podem mudar.", escape(config.AVISO_LEGAL)]
                telegram.enviar_foto(config.CANAL_ID, capa, "\n".join(partes), html=True)
                status.append(f"• Canal {config.CANAL_ID}: publicado ✅")
            except Exception as erro:  # noqa: BLE001
                status.append(f"• Canal: erro — {str(erro)[:120]}")

        # Reels / Story / TikTok — vaga reservada nos dias de Top 5
        limite_ig = config.INSTAGRAM_MAX_DIA
        if instagram.ativo() and (reservado or not limite_ig
                                  or relatorio.postados_hoje("instagram") < limite_ig):
            try:
                status.append(f"• Instagram: Reels publicado ✅ {instagram.publicar_reels(caminho, legenda_redes, capa=capa)}")
            except Exception as erro:  # noqa: BLE001
                status.append(f"• Instagram: erro — {str(erro)[:160]}")
        elif instagram.ativo():
            status.append("• Reels: pulado — limite do dia já atingido")
        if instagram.story_ativo() and video.duracao(caminho) <= 59:
            try:
                status.append(f"• Story no Instagram: publicado ✅ {instagram.publicar_story(caminho)}")
            except Exception as erro:  # noqa: BLE001
                status.append(f"• Story no Instagram: erro — {str(erro)[:160]}")
        limite_tt = config.TIKTOK_MAX_DIA
        if tiktok.ativo() and (reservado or not limite_tt or relatorio.postados_hoje("tiktok") < limite_tt):
            try:
                status.append(f"• TikTok: publicado ✅ {tiktok.publicar(caminho, legenda_redes)}")
            except Exception as erro:  # noqa: BLE001
                status.append(f"• TikTok: erro — {str(erro)[:160]}")
        elif tiktok.ativo():
            status.append("• TikTok: pulado — limite do dia já atingido")

        if config.ADMIN_CHAT_ID:
            try:
                telegram.enviar_video(config.ADMIN_CHAT_ID, caminho, f"🏆 Top {len(itens)}: {titulo_video}")
            except Exception:  # noqa: BLE001
                pass
        relatorio.registrar_post(f"Top {len(itens)} {titulo_video}", None,
                                 config.CANAL_ID or config.SITE_URL, status)
        historico = (_ler(CHAVE_HISTORICO, []) + [{"palavra": palavra, "data": _hoje()}])[-40:]
        supabase.gravar_config(CHAVE_HISTORICO, json.dumps(historico))
        try:
            from . import alertas
            alertas.depois_do_post(status)
        except Exception:  # noqa: BLE001
            pass
        enviar("\n".join([f"✅ Top {len(itens)} {titulo_video}", "", *status]))
        return status
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _previa(categoria: tuple, itens: list[dict], modo: str = "avaliados") -> str:
    palavra, titulo, teto = categoria
    linhas = [f"🏆 Prévia do Top 5 de hoje (sai às {HORA_POST}h):", _titulo(titulo, teto, modo), ""]
    for p, it in enumerate(itens, 1):
        extra = f" · ★ {it['nota']:.1f}".replace(".", ",") if it.get("nota") else f" · {it['loja']}"
        linhas.append(f"{p}. {it['nome'][:60]} — {formatar_preco(it['preco'])}{extra}")
        if it.get("motivo"):
            linhas.append(f"   ↳ {it['motivo']}")
    linhas += ["", "Não gostou? Mande /cancelar_top (o horário volta para os posts comuns)."]
    return "\n".join(linhas)


def se_for_hora(enviar) -> bool:
    """Chamado a cada rodada de 10 min: prévia às 19h e publicação às 20h nos dias de Top 5."""
    if not (config.VIDEO_TOP and supabase.ativo()):
        return False
    agora = datetime.now(FUSO)
    valor = str((supabase.ler_config(CHAVE_PROXIMO) or {}).get("valor", ""))
    if not valor.isdigit():
        supabase.gravar_config(CHAVE_PROXIMO, str(int(_proximo_dia_util(agora).timestamp())))
        return False
    if agora.timestamp() < int(valor):
        return False
    estado = estado_hoje()
    if agora.weekday() not in DIAS or agora.hour >= 23:
        supabase.gravar_config(CHAVE_PROXIMO, str(int(_proximo_dia_util(agora).timestamp())))
        return False
    if not estado:
        categoria = escolher_categoria(DIAS[agora.weekday()])
        modo = "custo" if len(_ler(CHAVE_HISTORICO, [])) % 2 == 0 else "avaliados"   # alterna os formatos
        itens = buscar_custo(categoria[0], categoria[2], []) if modo == "custo" else []
        if len(itens) < 3:
            modo, itens = "avaliados", buscar_produtos(categoria[0], categoria[2])
        if len(itens) < 3:
            supabase.gravar_config(CHAVE_ESTADO, json.dumps({"data": _hoje(), "fase": "sem_produtos"}))
            supabase.gravar_config(CHAVE_PROXIMO, str(int(_proximo_dia_util(agora + timedelta(hours=5)).timestamp())))
            enviar(f"🏆 Top 5 de hoje: não achei produtos suficientes em \"{categoria[1]}\". Fica para a próxima.")
            return False
        supabase.gravar_config(CHAVE_ESTADO, json.dumps({"data": _hoje(), "fase": "previa", "categoria": categoria,
                                                         "itens": itens, "modo": modo}, ensure_ascii=False))
        hora_post = agora.replace(hour=HORA_POST, minute=0, second=0, microsecond=0)
        supabase.gravar_config(CHAVE_PROXIMO, str(int(max(hora_post, agora + timedelta(minutes=30)).timestamp())))
        enviar(_previa(categoria, itens, modo))
        return True
    if estado.get("fase") == "previa":
        supabase.gravar_config(CHAVE_ESTADO, json.dumps({**estado, "fase": "postado"}, ensure_ascii=False))
        supabase.gravar_config(CHAVE_PROXIMO, str(int(_proximo_dia_util(agora + timedelta(hours=5)).timestamp())))
        palavra, titulo, teto = estado["categoria"]
        publicar(palavra, titulo, teto, estado["itens"], enviar, reservado=True,
                 modo=estado.get("modo", "avaliados"))
        return True
    supabase.gravar_config(CHAVE_PROXIMO, str(int(_proximo_dia_util(agora + timedelta(hours=5)).timestamp())))
    return False


def cancelar() -> str:
    estado = estado_hoje()
    if not estado or estado.get("fase") in ("postado", "sem_produtos"):
        return "Não tem Top 5 esperando hoje."
    if estado.get("fase") == "cancelado":
        return "O Top 5 de hoje já estava cancelado."
    supabase.gravar_config(CHAVE_ESTADO, json.dumps({**estado, "fase": "cancelado"}, ensure_ascii=False))
    return "🛑 Top 5 de hoje cancelado. O horário volta para os posts comuns."


def sob_demanda(texto: str, enviar) -> None:
    """/video_top fone bluetooth até 100"""
    m = re.search(r"(?:at[eé]|ate|<=?)\s*r?\$?\s*(\d+)", texto, re.I)
    teto = float(m.group(1)) if m else None
    palavra = re.sub(r"(?:at[eé]|ate|<=?)\s*r?\$?\s*\d+", "", texto, flags=re.I).strip()
    if not palavra:
        enviar("Use assim: /video_top fone bluetooth até 100\n(ou /video_top ssd nvme)")
        return
    enviar(f"🏆 Montando o Top 5 de \"{palavra}\"" + (f" até R$ {int(teto)}" if teto else "") + "… (uns 3 min)")
    itens = buscar_produtos(palavra, teto)
    if len(itens) < 3:
        enviar("Não achei produtos suficientes com nota boa nessa busca. Tente outra palavra ou um preço maior.")
        return
    publicar(palavra, palavra, teto, itens, enviar, reservado=False)


def custo_sob_demanda(texto: str, enviar) -> None:
    """/custo fone com dongle até 300"""
    palavra, teto, requisitos = separar_pedido(texto)
    if not palavra:
        enviar("Use assim: /custo fone com dongle até 300\n(ou /custo ssd nvme 1tb até 400)")
        return
    desc = palavra + (f" com {', '.join(requisitos)}" if requisitos else "") + (f" até R$ {int(teto)}" if teto else "")
    enviar(f"💡 Montando o Top 5 custo-benefício: {desc}… (uns 3 min)")
    itens = buscar_custo(palavra, teto, requisitos)
    if len(itens) < 3:
        if itens:     # poucos para um vídeo Top 5, mas vale mostrar para você
            linhas = [f"Só achei {len(itens)} que cumprem o pedido com nota boa (pouco para um vídeo):", ""]
            for i, it in enumerate(itens, 1):
                linhas += [f"{i}. {it['nome'][:70]} — {formatar_preco(it['preco'])} ({it['loja']})",
                           f"   ↳ {it.get('motivo', '')}", f"   🔗 {it['link']}", ""]
            linhas.append("Para postar um, mande o link para mim. Para um vídeo, tente um preço maior.")
            enviar("\n".join(linhas))
        else:
            enviar("Não achei produtos que cumpram o pedido com nota boa. "
                   "Tente sem o requisito ou com um preço maior.")
        return
    titulo = palavra + (f" com {', '.join(requisitos)}" if requisitos else "")
    publicar(palavra, titulo, teto, itens, enviar, reservado=False, modo="custo")
