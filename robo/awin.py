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
    return host.split(":")[0].removeprefix("www.").removeprefix("m.")


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
        if any(dom == d or dom.endswith("." + d) for d in loja["dominios"]):
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
    linhas += ["", "Para postar: mande o link NORMAL do produto (ex.: casasbahia.com.br/…).",
               "O robô troca sozinho pelo seu link de afiliada."]
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


def feeds() -> list[dict]:
    """Feeds das lojas que aceitaram você: [{fid, loja, loja_id, produtos}]."""
    if not feed_ativo():
        return []
    import csv
    import io
    r = requests.get(FEEDS.format(chave=config.AWIN_FEED_KEY), timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"feeds da Awin {r.status_code} (confira o AWIN_FEED_KEY)")
    saida = []
    for linha in csv.DictReader(io.StringIO(r.text)):
        status = (linha.get("Membership Status") or "").lower()
        if status and status not in ("active", "joined"):
            continue
        saida.append({"fid": linha.get("Feed ID"), "loja": linha.get("Advertiser Name", ""),
                      "loja_id": linha.get("Advertiser ID"), "produtos": int(linha.get("No of products") or 0)})
    return [f for f in saida if f["fid"]]


def _num(valor) -> float | None:
    try:
        v = float(str(valor).replace(",", "."))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def buscar_produtos(palavra: str, loja: str = "", teto: float | None = None, limite: int = 8) -> list[dict]:
    """Produtos dos feeds com a palavra no nome, em estoque, ordenados pelo desconto.

    Cada item: {nome, preco, preco_antigo, desconto, link (já é o SEU link de afiliada), imagem, loja, marca}.
    """
    import csv
    import gzip
    import io

    termos = [t for t in re.findall(r"[a-zà-ú0-9]{2,}", palavra.lower())]
    achados: list[dict] = []
    for feed in feeds():
        if loja and loja.lower() not in feed["loja"].lower():
            continue
        url = BAIXAR.format(chave=config.AWIN_FEED_KEY, fid=feed["fid"], colunas=COLUNAS)
        with requests.get(url, stream=True, timeout=180) as r:
            if r.status_code >= 300:
                print(f"::warning::Feed Awin {feed['loja']}: {r.status_code}")
                continue
            r.raw.decode_content = False
            leitor = csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=r.raw), encoding="utf-8", errors="replace"))
            for n, p in enumerate(leitor):
                if n > MAX_LINHAS:
                    break
                nome = p.get("product_name") or ""
                baixo = nome.lower()
                if termos and not all(t in baixo for t in termos):
                    continue
                if str(p.get("in_stock", "1")).strip() in ("0", "false", "no"):
                    continue
                preco = _num(p.get("search_price"))
                if not preco or (teto and preco > teto):
                    continue
                antigo = _num(p.get("rrp_price")) or _num(p.get("product_price_old"))
                antigo = antigo if antigo and antigo > preco * 1.02 else None
                achados.append({
                    "nome": nome.strip(), "preco": preco, "preco_antigo": antigo,
                    "desconto": round((1 - preco / antigo) * 100) if antigo else 0,
                    "link": p.get("aw_deep_link") or "", "imagem": p.get("merchant_image_url") or p.get("aw_image_url") or "",
                    "loja": p.get("merchant_name") or feed["loja"], "marca": p.get("brand_name") or "",
                    "id": p.get("aw_product_id") or "",
                })
    from . import marcas
    achados = [a for a in achados if a["link"]]
    achados.sort(key=lambda a: (-(a["desconto"] + (15 if marcas.conhecida(a["nome"]) or a["marca"] else 0)), a["preco"]))
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
    link = item["link"] + ("&" if "?" in item["link"] else "?") + f"clickref={origem}"
    linhas = [link, f"nome: {item['nome'][:150]}", f"loja: {item['loja']}", f"preco: {item['preco']:.2f}".replace(".", ",")]
    if item.get("preco_antigo"):
        linhas.append(f"de: {item['preco_antigo']:.2f}".replace(".", ","))
    if item.get("imagem"):
        linhas.append(f"foto: {item['imagem']}")
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
                                                  if it.get("preco_antigo") else "") + f" · {it['loja']}",
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
