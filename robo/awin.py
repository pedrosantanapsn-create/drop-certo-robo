"""Awin (Casas Bahia, KaBuM! e outras lojas da rede Awin) pela API oficial de afiliados.

O que o robô faz com a Awin:
  • Converte sozinho qualquer link de loja Awin em que você foi ACEITA para o SEU link
    de afiliada (Link Builder) — você manda o link normal da Casas Bahia e pronto.
    Canal e site recebem links com marcas diferentes (clickref "canal" / "site").
  • Bloqueia o post se a loja é da Awin mas você ainda não foi aceita (sem comissão).
  • /awin mostra seu ID de afiliada e as lojas aceitas / pendentes.
  • O relatório de segunda mostra as vendas e a comissão da Awin.

Segredo no GitHub: AWIN_TOKEN (Awin → seu perfil → API Credentials).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

from . import config, supabase

API = "https://api.awin.com"
CHAVE_CACHE = "awin_programas"
CACHE_HORAS = 12
RE_JA_AWIN = re.compile(r"awin1\.com/|tidd\.ly/|awin\.link/", re.I)

_cache: dict | None = None


def ativo() -> bool:
    return bool(config.AWIN_TOKEN)


def _get(caminho: str, **params) -> dict | list:
    r = requests.get(f"{API}{caminho}", params=params, timeout=30,
                     headers={"Authorization": f"Bearer {config.AWIN_TOKEN}"})
    if r.status_code == 401:     # algumas contas só aceitam o token no endereço
        r = requests.get(f"{API}{caminho}", params={**params, "accessToken": config.AWIN_TOKEN}, timeout=30)
    if r.status_code == 401:
        raise RuntimeError("a Awin recusou o token (AWIN_TOKEN errado ou vencido)")
    if r.status_code >= 300:
        raise RuntimeError(f"Awin {r.status_code}: {r.text[:150]}")
    return r.json()


def _post(caminho: str, corpo: dict) -> dict:
    r = requests.post(f"{API}{caminho}", json=corpo, timeout=30,
                      headers={"Authorization": f"Bearer {config.AWIN_TOKEN}"})
    if r.status_code == 401:
        r = requests.post(f"{API}{caminho}", json=corpo, timeout=30, params={"accessToken": config.AWIN_TOKEN})
    if r.status_code >= 300:
        raise RuntimeError(f"Awin {r.status_code}: {r.text[:150]}")
    return r.json()


def _dominio(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return host.split(":")[0].lstrip("*.").removeprefix("www.").removeprefix("m.")


def _carregar() -> dict:
    """{'publisher': id, 'nome': ..., 'lojas': [{id, nome, dominios, status}]} — guardado 12 h."""
    global _cache
    if _cache is not None:
        return _cache
    if supabase.ativo():
        try:
            guardado = json.loads((supabase.ler_config(CHAVE_CACHE) or {}).get("valor") or "{}")
            if guardado and time.time() - guardado.get("t", 0) < CACHE_HORAS * 3600:
                _cache = guardado
                return _cache
        except ValueError:
            pass
    contas = _get("/accounts").get("accounts") or []
    pub = next((c for c in contas if str(c.get("accountType", "")).lower() == "publisher"), None)
    if not pub:
        raise RuntimeError("não achei uma conta de afiliado (publisher) nesse token da Awin")
    lojas = []
    for status in ("joined", "pending"):
        for p in _get(f"/publishers/{pub['accountId']}/programmes", relationship=status) or []:
            dominios = {_dominio(d.get("domain", "")) for d in (p.get("validDomains") or []) if d.get("domain")}
            if p.get("displayUrl"):
                dominios.add(_dominio(p["displayUrl"]))
            lojas.append({"id": p.get("id"), "nome": p.get("name", ""), "status": status,
                          "dominios": sorted(d for d in dominios if d)})
    _cache = {"t": time.time(), "publisher": pub["accountId"], "nome": pub.get("accountName", ""), "lojas": lojas}
    if supabase.ativo():
        supabase.gravar_config(CHAVE_CACHE, json.dumps(_cache, ensure_ascii=False))
    return _cache


def loja_do_link(link: str) -> dict | None:
    """A loja Awin (aceita ou pendente) desse link, ou None se não é loja da Awin."""
    if not ativo() or not link:
        return None
    dom = _dominio(link)
    for loja in _carregar()["lojas"]:
        if any(dom == d.lstrip("*.") or dom.endswith("." + d.lstrip("*.")) for d in loja["dominios"]):
            return loja
    return None


def e_link_awin(link: str) -> bool:
    return bool(RE_JA_AWIN.search(link or ""))


def link_afiliado(destino: str, advertiser_id: int, clickref: str = "dropcerto") -> str:
    dados = _post(f"/publishers/{_carregar()['publisher']}/linkbuilder/generate", {
        "advertiserId": int(advertiser_id), "destinationUrl": destino,
        "parameters": {"clickref": clickref}, "shorten": False})
    # o link longo leva o endereço da loja dentro (ued=): o site e o relatório reconhecem a loja
    link = dados.get("url") or dados.get("shortUrl")
    if not link:
        raise RuntimeError(f"a Awin não gerou o link ({str(dados)[:120]})")
    return link


def converter(link: str) -> tuple[str, str, str]:
    """(link_site, link_canal, aviso). link_site vazio = não postar (loja Awin sem aceite)."""
    loja = loja_do_link(link)
    if not loja:
        return link, link, ""
    if loja["status"] != "joined":
        return "", "", (f"⚠️ {loja['nome']} é da Awin, mas o seu cadastro nessa loja ainda está pendente — "
                        "sem aceite não há comissão. 🛑 Não postei. (/awin mostra a situação)")
    site = link_afiliado(link, loja["id"], "site")
    try:
        canal = link_afiliado(link, loja["id"], "canal")
    except Exception:  # noqa: BLE001
        canal = site
    return site, canal, f"link de afiliada da Awin gerado ({loja['nome']}) ✅"


def nome_loja(link: str) -> str:
    try:
        loja = loja_do_link(link)
    except Exception:  # noqa: BLE001
        return ""
    return loja["nome"] if loja else ""


def resumo() -> str:
    if not ativo():
        return ("A Awin ainda não está ligada.\n\n1. No site da Awin: seu nome (canto de cima) → API Credentials → "
                "copie o token.\n2. No GitHub do robô: Settings → Secrets and variables → Actions → "
                "New repository secret → nome AWIN_TOKEN → cole o token.\nDepois mande /awin de novo.")
    global _cache
    _cache = None
    if supabase.ativo():
        supabase.gravar_config(CHAVE_CACHE, "")       # força ler de novo
    dados = _carregar()
    aceitas = [l for l in dados["lojas"] if l["status"] == "joined"]
    pendentes = [l for l in dados["lojas"] if l["status"] == "pending"]
    linhas = [f"🔗 Awin ligada ✅ — conta {dados['nome']} · seu ID de afiliada (awinaffid): {dados['publisher']}", ""]
    linhas.append(f"✅ Lojas que aceitaram você ({len(aceitas)}):")
    linhas += [f"   • {l['nome']} — {', '.join(l['dominios'][:2]) or 'sem domínio'}" for l in aceitas] or ["   (nenhuma ainda)"]
    if pendentes:
        linhas += ["", f"⏳ Aguardando aprovação ({len(pendentes)}):"]
        linhas += [f"   • {l['nome']}" for l in pendentes]
    exemplo = aceitas[0]["dominios"][0] if aceitas and aceitas[0]["dominios"] else "site da loja"
    linhas += ["", f"Para postar: mande o link NORMAL do produto (ex.: {exemplo}/…).",
               "O robô troca sozinho pelo seu link de afiliada.",
               "Buscar produtos: /kabum ssd 1tb · /awin_ofertas monitor até 900 · cupons: /awin_cupons",
               "Loja que não aparece aqui ainda não aceitou você (veja em Anunciantes → Meus programas na Awin)."]
    return "\n".join(linhas)


def vendas(dias: int = 7) -> list[dict]:
    """Vendas pela Awin nos últimos dias: [{loja, valor, comissao, status, clickref}]."""
    if not ativo():
        return []
    dados = _carregar()
    fim = datetime.now()
    inicio = fim - timedelta(days=min(dias, 31))
    lista = _get(f"/publishers/{dados['publisher']}/transactions/",
                 startDate=inicio.strftime("%Y-%m-%dT00:00:00"), endDate=fim.strftime("%Y-%m-%dT23:59:59"),
                 timezone="UTC")
    nomes = {l["id"]: l["nome"] for l in dados["lojas"]}
    saida = []
    for t in lista or []:
        saida.append({
            "loja": nomes.get(t.get("advertiserId"), str(t.get("advertiserId"))),
            "valor": float((t.get("saleAmount") or {}).get("amount") or 0),
            "comissao": float((t.get("commissionAmount") or {}).get("amount") or 0),
            "status": str(t.get("commissionStatus") or ""),
            "clickref": str((t.get("clickRefs") or {}).get("clickRef") or ""),
        })
    return saida


# ---------------------------------------------------------------------------
# Busca de produtos (feeds de produtos da Awin) — igual ao /shopee
# Precisa do segredo AWIN_FEED_KEY (Awin → Ferramentas → Create-a-Feed → "API Key").
# ---------------------------------------------------------------------------
FEEDS = "https://productdata.awin.com/datafeed/list/apikey/{chave}"
COLUNAS = ("aw_deep_link,product_name,aw_product_id,merchant_image_url,aw_image_url,search_price,"
           "rrp_price,product_price_old,brand_name,in_stock,merchant_name,merchant_id,merchant_category")
BAIXAR = ("https://productdata.awin.com/datafeed/download/apikey/{chave}/language/any/fid/{fid}"
          "/columns/{colunas}/format/csv/delimiter/%2C/compression/gzip/adultcontent/1/")
MAX_LINHAS = 400_000            # protege o tempo da rodada em feeds gigantes


def feed_ativo() -> bool:
    return bool(config.AWIN_FEED_KEY)


def _lista_url() -> str:
    """AWIN_FEED_KEY pode ser o endereço inteiro da "Lista de Feed" (formato novo) ou só a chave (antigo)."""
    chave = config.AWIN_FEED_KEY.strip()
    return chave if chave.startswith("http") else FEEDS.format(chave=chave)


def _campo(linha: dict, *nomes: str) -> str:
    """Valor da primeira coluna que existir (os feeds antigo e novo usam nomes diferentes)."""
    baixas = {k.strip().lower(): v for k, v in linha.items() if k}
    for nome in nomes:
        valor = baixas.get(nome.lower())
        if valor not in (None, ""):
            return str(valor).strip()
    return ""


def _ler_csv(conteudo: bytes):
    """Linhas de um CSV (com ou sem gzip, vírgula/ponto e vírgula/tab)."""
    import csv
    import gzip
    import io
    if conteudo[:2] == b"\x1f\x8b":
        conteudo = gzip.decompress(conteudo)
    texto = conteudo.decode("utf-8", errors="replace").lstrip("\ufeff")
    try:     # só o separador; o resto do padrão Excel (aspas dobradas) evita erro com 2.5" nos nomes
        separador = csv.Sniffer().sniff(texto[:5000], delimiters=",;\t|").delimiter
    except csv.Error:
        separador = ","
    return csv.DictReader(io.StringIO(texto), delimiter=separador)


def feeds() -> list[dict]:
    """Feeds das lojas que aceitaram você: [{fid, loja, loja_id, produtos, url}]."""
    if not feed_ativo():
        return []
    r = requests.get(_lista_url(), timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"lista de feeds da Awin {r.status_code} (confira o AWIN_FEED_KEY)")
    saida = []
    for linha in _ler_csv(r.content):
        status = _campo(linha, "Membership Status", "membership_status", "status").lower()
        if status and status not in ("active", "joined", "ativo"):
            continue
        saida.append({"fid": _campo(linha, "Feed ID", "feed_id", "fid"),
                      "loja": _campo(linha, "Advertiser Name", "advertiser_name"),
                      "loja_id": _campo(linha, "Advertiser ID", "advertiser_id"),
                      "produtos": int(float(_campo(linha, "No of products", "number_of_products") or 0)),
                      "url": _campo(linha, "URL", "url", "Download URL")})
    return [f for f in saida if f["fid"] or f["url"]]


def _num(valor) -> float | None:
    achado = re.search(r"\d[\d.,]*", str(valor or ""))
    if not achado:
        return None
    bruto = achado.group(0)
    if "," in bruto and "." in bruto:          # 1.299,90 ou 1,299.90
        bruto = bruto.replace(".", "").replace(",", ".") if bruto.rfind(",") > bruto.rfind(".") else bruto.replace(",", "")
    elif "," in bruto:
        bruto = bruto.replace(",", ".")
    try:
        v = float(bruto)
        return v if v > 0 else None
    except ValueError:
        return None


def buscar_produtos(palavra: str, loja: str = "", teto: float | None = None, limite: int = 8) -> list[dict]:
    """Produtos dos feeds com a palavra no nome, em estoque, ordenados pelo desconto.

    Cada item: {nome, preco, preco_antigo, desconto, link, imagem, loja, marca, id}.
    O link é o SEU link de afiliada quando o feed já traz (aw_deep_link); senão é o link da loja
    e o robô converte pelo Link Builder na hora de postar.
    """
    termos = [t for t in re.findall(r"[a-zà-ú0-9]{2,}", palavra.lower())]
    achados: list[dict] = []
    for feed in feeds():
        if loja and loja.lower() not in feed["loja"].lower():
            continue
        url = feed["url"] or BAIXAR.format(chave=config.AWIN_FEED_KEY, fid=feed["fid"], colunas=COLUNAS)
        r = requests.get(url, timeout=180)
        if r.status_code >= 300:
            print(f"::warning::Feed Awin {feed['loja']}: {r.status_code}")
            continue
        for n, p in enumerate(_ler_csv(r.content)):
            if n > MAX_LINHAS:
                break
            nome = _campo(p, "product_name", "title", "name")
            if termos and not all(t in nome.lower() for t in termos):
                continue
            estoque = _campo(p, "in_stock", "availability", "stock_status").lower()
            if estoque in ("0", "false", "no", "out of stock", "out_of_stock", "fora de estoque"):
                continue
            venda = _num(_campo(p, "sale_price", "search_price", "display_price", "store_price"))
            cheio = _num(_campo(p, "rrp_price", "product_price_old", "price"))
            preco = venda or cheio
            if not preco or (teto and preco > teto):
                continue
            antigo = cheio if cheio and cheio > preco * 1.02 else None
            prazo = ""                         # KaBuM: search_price é à vista; custom_3 é o total parcelado
            meses = re.search(r"(\d+)", _campo(p, "custom_1")) if "install" in _campo(p, "custom_1").lower() else None
            total = _num(_campo(p, "custom_3"))
            if meses and total and total > preco * 1.01:
                prazo = f"{meses.group(1)}x — total R$ {total:.2f}".replace(".", ",")
            achados.append({
                "prazo": prazo,
                "nome": nome, "preco": preco, "preco_antigo": antigo,
                "desconto": round((1 - preco / antigo) * 100) if antigo else 0,
                "link": _campo(p, "aw_deep_link", "tracking_url", "link", "merchant_deep_link"),
                "imagem": _campo(p, "merchant_image_url", "aw_image_url", "image_link", "image_url"),
                "loja": _campo(p, "merchant_name") or feed["loja"],
                "marca": _campo(p, "brand_name", "brand"),
                "id": _campo(p, "aw_product_id", "id", "merchant_product_id"),
            })
    from . import marcas
    from .ranking import RE_ACESSORIO
    pediu_acessorio = bool(RE_ACESSORIO.search(palavra))
    primeiro = termos[0] if termos else ""

    def relevancia(a: dict) -> float:
        inicio = " ".join(a["nome"].lower().split()[:4])
        return (a["desconto"] + (15 if marcas.conhecida(a["nome"]) or a["marca"] else 0)
                + (20 if primeiro and primeiro in inicio else 0))

    achados = [a for a in achados if a["link"]
               and (pediu_acessorio or not RE_ACESSORIO.search(" ".join(a["nome"].split()[:5])))]
    achados.sort(key=lambda a: (-relevancia(a), a["preco"]))
    vistos, saida = set(), []
    for a in achados:                       # sem repetir o mesmo produto
        chave = re.sub(r"\W+", "", a["nome"].lower())[:50]
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(a)
        if a["id"]:
            from . import precos
            precos.registrar(f"awin:{a['id']}", a["preco"])      # histórico próprio (desconto falso etc.)
        if len(saida) >= limite:
            break
    return saida


def texto_fila(item: dict, origem: str = "fila") -> str:
    """Texto da oferta para a fila: link + preço + nome + foto (o robô não precisa abrir a loja)."""
    link = item["link"]
    if e_link_awin(link):
        link += ("&" if "?" in link else "?") + f"clickref={origem}"
    linhas = [link, f"nome: {item['nome'][:150]}", f"loja: {item['loja']}", f"preco: {item['preco']:.2f}".replace(".", ",")]
    if item.get("preco_antigo"):
        linhas.append(f"de: {item['preco_antigo']:.2f}".replace(".", ","))
    if item.get("imagem"):
        linhas.append(f"foto: {item['imagem']}")
    if item.get("prazo"):
        linhas.append(f"obs: preço à vista; parcelado em {item['prazo']}")
    return "\n".join(linhas)


def mensagem_produtos(itens: list[dict], titulo: str) -> str:
    from .produto import formatar_preco
    if not itens:
        return f"{titulo}\n\nNão achei produtos com essa palavra nos feeds das lojas que aceitaram você."
    linhas = [titulo, ""]
    for i, it in enumerate(itens, 1):
        linhas += [
            f"A{i}. {it['nome'][:90]}",
            f"💰 {formatar_preco(it['preco'])}" + (f" (antes {formatar_preco(it['preco_antigo'])} · -{it['desconto']}%)"
                                                  if it.get("preco_antigo") else "")
            + (" à vista" if it.get("prazo") else "") + f" · {it['loja']}",
            "",
        ]
    linhas += ["➕ Pôr na fila: /add A1 A3  ·  todos: /add awin",
               "ℹ️ Preço do feed da loja (atualizado pela loja 1x por dia, mais ou menos): confira antes de postar."]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Cupons e promoções das lojas que aceitaram você (Offers API)
# ---------------------------------------------------------------------------
def cupons(limite: int = 15) -> list[dict]:
    dados = _post(f"/publisher/{_carregar()['publisher']}/promotions", {
        "filters": {"membership": "joined", "status": "active"},
        "pagination": {"page": 1, "pageSize": 100}})
    saida = []
    for p in dados.get("data") or []:
        voucher = p.get("voucher") or {}
        saida.append({"loja": (p.get("advertiser") or {}).get("name", ""), "titulo": p.get("title", ""),
                      "codigo": voucher.get("code") or "", "fim": str(p.get("endDate") or "")[:10],
                      "regras": p.get("terms") or p.get("description") or "",
                      "link": p.get("urlTracking") or p.get("url") or ""})
    saida.sort(key=lambda c: (not c["codigo"], c["fim"] or "9999"))
    return saida[:limite]


def mensagem_cupons(lista: list[dict]) -> str:
    if not lista:
        return "🎟️ Nenhum cupom ou promoção ativa agora nas lojas Awin que aceitaram você."
    linhas = ["🎟️ Cupons e promoções das suas lojas Awin:", ""]
    for c in lista:
        linhas.append(f"• {c['loja']} — {c['titulo'][:90]}")
        if c["codigo"]:
            linhas.append(f"   Código: {c['codigo']}" + (f" · até {c['fim']}" if c["fim"] else ""))
        elif c["fim"]:
            linhas.append(f"   Até {c['fim']}")
        if c["link"]:
            linhas.append(f"   🔗 {c['link']}")
        linhas.append("")
    linhas.append("Para divulgar um: /cupom CODIGO descrição + o link (mande /cupom para ver o modelo).")
    return "\n".join(linhas)
