"""Ajudante do PC — lado do robô.

O Mercado Livre só gera o meli.la (o link que conta a comissão) para quem está logada.
O "ajudante" é um programa no PC da dona: ele usa o Edge logado na conta dela, gera o
meli.la de cada produto pedido e devolve aqui. O robô do GitHub:

  1. pede:      ajudante.pedir("ml:MLB123", url_do_produto, {"texto": oferta})
  2. o ajudante (quando o PC está ligado) gera o meli.la e marca o pedido como "pronto";
  3. importa:   ajudante.importar() põe a oferta na fila com o meli.la dela.

Tabela: ajudante_pedidos (ver supabase/ajudante.sql). Desligar: variável AJUDANTE=false.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from urllib.parse import quote_plus

from . import config, fila, supabase

TABELA = "ajudante_pedidos"
VIVO_MINUTOS = 20           # ajudante "ligado" = deu sinal nos últimos minutos
VALIDADE_HORAS = 48         # pedido que ninguém atendeu nesse tempo é descartado


def ativo() -> bool:
    return bool(config.AJUDANTE and supabase.ativo())


def _url() -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{TABELA}"


def _ler(params: dict) -> list[dict]:
    r = requests.get(_url(), headers=supabase._cabecalhos(), params=params, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"ajudante: Supabase {r.status_code} {r.text[:120]}")
    return r.json()


def _mudar(ident: str, campos: dict) -> None:
    r = requests.patch(_url(), headers=supabase._cabecalhos({"Content-Type": "application/json",
                                                             "Prefer": "return=minimal"}),
                       params={"id": f"eq.{ident}"}, json=campos, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"ajudante: Supabase {r.status_code} {r.text[:120]}")


def sinal() -> dict | None:
    """Último sinal de vida do ajudante: {'quando': datetime, 'precisa_login': bool} ou None."""
    linhas = _ler({"chave": "eq._batimento", "select": "feito_em,dados"})
    if not linhas or not linhas[0].get("feito_em"):
        return None
    quando = datetime.fromisoformat(str(linhas[0]["feito_em"]).replace("Z", "+00:00"))
    return {"quando": quando, "precisa_login": bool((linhas[0].get("dados") or {}).get("precisa_login"))}


def ligado() -> bool:
    try:
        s = sinal()
    except Exception:  # noqa: BLE001
        return False
    return bool(s and datetime.now(timezone.utc) - s["quando"] < timedelta(minutes=VIVO_MINUTOS))


def usado_recentemente(dias: int = 3) -> bool:
    """O ajudante deu sinal nos últimos dias? (só então vale pedir links para a fila automática)"""
    try:
        s = sinal()
    except Exception:  # noqa: BLE001
        return False
    return bool(s and datetime.now(timezone.utc) - s["quando"] < timedelta(days=dias))


def pedir(chave: str, url: str, dados: dict, loja: str = "ml") -> bool:
    """Cria o pedido (se já existe um igual, não repete). True = pedido novo criado."""
    r = requests.post(_url(), headers=supabase._cabecalhos({
        "Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates,return=representation"}),
        params={"on_conflict": "chave"}, json={"loja": loja, "chave": chave, "url": url, "dados": dados},
        timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"ajudante: Supabase {r.status_code} {r.text[:120]}")
    return bool(r.json())


# Buscas que o navegador da dona faz nas lojas que bloqueiam o robô
BUSCAS = {
    "terabyte": {"loja": "busca_terabyte", "nome": "Terabyte", "codigo": "T",
                 "url": "https://www.terabyteshop.com.br/busca?str={termo}"},
    "amazon": {"loja": "busca_amazon", "nome": "Amazon", "codigo": "Z",
               "url": "https://www.amazon.com.br/s?k={termo}"},
}


def pedir_busca(qual: str, termo: str, teto: float | None = None) -> bool:
    """Pede ao ajudante para procurar `termo` na loja (terabyte/amazon). O resultado chega em importar()."""
    b = BUSCAS[qual]
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return pedir(f"busca:{qual}:{termo.lower()[:60]}:{carimbo}", b["url"].format(termo=quote_plus(termo)),
                 {"termo": termo, "teto": teto}, loja=b["loja"])


def _num(valor) -> float | None:
    try:
        v = float(valor)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _mensagem_busca(qual: str, dados: dict) -> str:
    """Lista T1/Z1… com o que o ajudante achou; guarda os textos prontos para o /add."""
    import re

    from . import amazon, sugestoes, terabyte
    from .produto import formatar_preco
    b = BUSCAS[qual]
    termo, teto = str(dados.get("termo") or ""), _num(dados.get("teto"))
    palavras = re.findall(r"[a-zà-ú0-9]{2,}", termo.lower())
    itens = []
    for it in dados.get("resultado") or []:
        nome, preco = str(it.get("nome") or "").strip(), _num(it.get("preco"))
        if not (nome and preco and it.get("link")) or (teto and preco > teto):
            continue
        if palavras and not all(re.search(rf"\b{re.escape(p)}", nome.lower()) for p in palavras):
            continue
        antigo = _num(it.get("preco_antigo"))
        antigo = antigo if antigo and antigo > preco * 1.02 else None
        itens.append({**it, "nome": nome, "preco": preco, "preco_antigo": antigo,
                      "desconto": round((1 - preco / antigo) * 100) if antigo else 0})
    itens.sort(key=lambda i: (-i["desconto"], i["preco"]))
    itens = itens[:8]
    if not itens:
        return f"🧩 {b['nome']} — \"{termo}\": o ajudante não achou produtos com essa busca."
    textos, linhas = [], [f"🧩 {b['nome']} — {termo} (busca feita no seu navegador)", ""]
    for n, it in enumerate(itens, 1):
        if qual == "amazon":
            link = amazon.link_com_minha_tag(str(it["link"]))[0] or str(it["link"])
            obs = ""
        else:
            link = terabyte.link_com_meu_codigo(str(it["link"]))[0]
            obs = "\nobs: preço à vista no Pix ou boleto"
        texto = f"{link}\nnome: {it['nome'][:150]}\npreco: " + f"{it['preco']:.2f}".replace(".", ",")
        if it["preco_antigo"]:
            texto += "\nde: " + f"{it['preco_antigo']:.2f}".replace(".", ",")
        if str(it.get("imagem") or "").startswith("http"):
            texto += f"\nfoto: {it['imagem']}"
        textos.append(texto + obs)
        linhas += [f"{b['codigo']}{n}. {it['nome'][:90]}",
                   f"💰 {formatar_preco(it['preco'])}" + (f" (antes {formatar_preco(it['preco_antigo'])} · "
                                                          f"-{it['desconto']}%)" if it["preco_antigo"] else ""), ""]
    sugestoes._guardar(b["codigo"], textos)
    linhas += [f"➕ Pôr na fila: /add {b['codigo']}1 {b['codigo']}3",
               "ℹ️ Preço visto agora na loja pelo seu navegador; confira antes de postar."]
    return "\n".join(linhas)


def pendentes() -> int:
    return len(_ler({"status": "eq.pendente", "loja": "neq._sistema", "select": "id"}))


def importar(avisar) -> int:
    """Põe na fila as ofertas cujo link o ajudante já gerou; avisa erros e pedido de login."""
    if not ativo():
        return 0
    postas = 0
    for p in _ler({"status": "eq.pronto", "select": "id,loja,chave,url,link,dados", "order": "feito_em.asc",
                   "limit": "20"}):
        dados = p.get("dados") or {}
        if str(p.get("loja", "")).startswith("busca_"):        # resultado de busca: manda a lista
            qual = str(p["loja"]).replace("busca_", "")
            try:
                avisar(_mensagem_busca(qual, dados))
            except Exception as erro:  # noqa: BLE001
                avisar(f"🧩 Busca: não consegui montar a lista ({str(erro)[:150]})")
            _mudar(p["id"], {"status": "importado"})
            continue
        texto = str(dados.get("texto") or p["url"])
        original = str(dados.get("link_original") or p["url"])
        texto = texto.replace(original, p["link"]) if original in texto else f"{p['link']}\n{texto}"
        fila.adicionar([texto])
        _mudar(p["id"], {"status": "importado"})
        postas += 1
    if postas:
        avisar(f"🧩 O ajudante gerou {postas} link(s) meli.la seu(s) — já estão na fila. /fila para ver.")

    for p in _ler({"status": "eq.erro", "loja": "neq._sistema", "select": "id,loja,url,erro", "limit": "10"}):
        if str(p.get("loja", "")).startswith("busca_"):
            avisar(f"🧩 O ajudante não conseguiu fazer a busca:\n{p['url']}\nMotivo: {str(p.get('erro'))[:600]}")
        else:
            avisar(f"🧩 O ajudante não conseguiu gerar o link de:\n{p['url']}\nMotivo: {str(p.get('erro'))[:200]}\n"
                   "Gere o meli.la no app e mande para mim.")
        _mudar(p["id"], {"status": "avisado"})

    limite = (datetime.now(timezone.utc) - timedelta(hours=VALIDADE_HORAS)).isoformat()
    velhos = _ler({"status": "eq.pendente", "loja": "neq._sistema", "criado_em": f"lt.{limite}", "select": "id"})
    for p in velhos:
        _mudar(p["id"], {"status": "vencido"})

    # O ajudante avisou que caiu o login do Mercado Livre: avisa a dona 1 vez por dia
    try:
        s = sinal()
        if s and s["precisa_login"]:
            hoje = datetime.now(fila.FUSO).strftime("%Y-%m-%d")
            if (supabase.ler_config("ajudante_aviso_login") or {}).get("valor") != hoje:
                supabase.gravar_config("ajudante_aviso_login", hoje)
                avisar("🧩 O ajudante do PC perdeu o login do Mercado Livre.\nNo PC, abra \"2 - Fazer login.bat\", "
                       "entre na sua conta e depois ligue o ajudante de novo.")
    except Exception as erro:  # noqa: BLE001
        print("Ajudante (sinal):", erro)
    return postas
