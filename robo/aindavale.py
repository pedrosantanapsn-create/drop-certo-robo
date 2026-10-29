"""🔁 "Ainda vale!" — reposta no canal a oferta que já provou que interessa.

Uma vez por dia (18h), o robô procura no site uma oferta da Shopee ou do Mercado
Livre postada há 3–10 dias que teve clique, confere o preço AGORA pela API oficial e,
se continua igual ou mais barato, posta de novo no canal com o selo "AINDA VALE!".

Nunca reposta o mesmo produto duas vezes e não usa Amazon (o preço da Amazon não
dá para conferir sem print — CDC art. 37).
Desligar: variável AINDA_VALE = false.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta

import requests

from . import canal, config, mercadolivre, shopee, supabase, telegram, verificador
from .fila import FUSO
from .produto import Produto, formatar_preco

CHAVE = "aindavale_proximo"
CHAVE_FEITOS = "aindavale_feitos"
HORA = 18


def _proximo(agora: datetime) -> datetime:
    alvo = agora.replace(hour=HORA, minute=0, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=1)


def _candidatos(agora: datetime) -> list[dict]:
    cab = supabase._cabecalhos()
    r = requests.get(f"{config.SUPABASE_URL}/rest/v1/cliques", headers=cab, timeout=30,
                     params={"select": "produto_id", "criado_em": f"gte.{(agora - timedelta(days=10)).isoformat()}",
                             "limit": 5000})
    r.raise_for_status()
    cliques = Counter(str(c.get("produto_id") or "") for c in r.json() if c.get("produto_id"))
    if not cliques:
        return []
    ids = ",".join(f'"{i}"' for i in list(cliques)[:150] if i.replace("-", "").isalnum())
    if not ids:
        return []
    colunas = ",".join(c for c in ("id", config.COL_NOME, config.COL_PRECO, config.COL_PRECO_ANTIGO,
                                   config.COL_LINK, config.COL_IMAGEM, "criado_em") if c and c != "-")
    r = requests.get(f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}", headers=cab, timeout=30,
                     params={"select": colunas, "id": f"in.({ids})", "ativo": "eq.true",
                             "criado_em": f"lte.{(agora - timedelta(days=3)).isoformat()}"})
    r.raise_for_status()
    produtos = [p for p in r.json() if p.get(config.COL_PRECO) and p.get(config.COL_IMAGEM)
                and (shopee.e_shopee(str(p.get(config.COL_LINK))) or mercadolivre.e_mercadolivre(str(p.get(config.COL_LINK))))]
    return sorted(produtos, key=lambda p: -cliques.get(str(p["id"]), 0))


def postar_se_for_hora(avisar) -> bool:
    if not (config.AINDA_VALE and config.CANAL_ID and supabase.ativo()):
        return False
    agora = datetime.now(FUSO)
    valor = str((supabase.ler_config(CHAVE) or {}).get("valor", ""))
    if valor.isdigit() and agora.timestamp() < int(valor):
        return False
    supabase.gravar_config(CHAVE, str(int(_proximo(agora).timestamp())))
    if not valor.isdigit() or agora.hour >= 21:
        return False                     # primeira vez (só marca) ou passou muito da hora
    try:
        feitos = json.loads((supabase.ler_config(CHAVE_FEITOS) or {}).get("valor") or "[]")
    except ValueError:
        feitos = []
    for p in _candidatos(agora)[:8]:
        if str(p["id"]) in feitos:
            continue
        link = str(p[config.COL_LINK])
        estado, lido = verificador.situacao(link)
        preco_site = float(p[config.COL_PRECO])
        if estado != "ok" or not lido.preco or lido.preco > preco_site * 1.02:
            continue
        produto = Produto(link=link, nome=str(p.get(config.COL_NOME) or lido.nome), preco=lido.preco,
                          preco_antigo=lido.preco_antigo if (lido.preco_antigo or 0) > lido.preco else None)
        produto.site_id = str(p["id"])
        destino = link
        if shopee.e_shopee(link) and config.MARCAR_ORIGEM_SHOPEE:
            try:
                origem = shopee.ler(link).get("link_produto")
                destino = shopee.link_afiliado(origem, "aindavale") if origem else link
            except Exception:  # noqa: BLE001
                destino = link
        topo = "🔁 <b>AINDA VALE!</b> — uma das ofertas que vocês mais clicaram continua com preço bom"
        legenda = canal.legenda(produto, link=destino, topo=topo)
        telegram.enviar_foto_url(config.CANAL_ID, str(p[config.COL_IMAGEM]), legenda, html=True)
        supabase.gravar_config(CHAVE_FEITOS, json.dumps((feitos + [str(p["id"])])[-300:]))
        avisar(f"🔁 \"Ainda vale!\" no canal: {produto.nome[:60]} — {formatar_preco(produto.preco)}")
        return True
    return False

