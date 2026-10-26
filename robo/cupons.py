"""Posts de cupom no canal, com passo a passo e horário marcado.

    /cupom DROP10 R$ 20 off acima de R$ 100
    loja: Shopee
    https://s.shopee.com.br/xxxx
    validade: 31/10
    1. Resgate o cupom na página da loja
    2. Adicione os produtos no carrinho
    3. Na finalização, escolha o cupom DROP10
    hora: 00:00            (opcional — sem isso, posta na hora)

Cupons que "liberam à meia-noite" podem ser marcados antes: o robô guarda e posta
no horário (chave "cupom_proximo" acorda o robô no minuto certo).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from html import escape

from . import amazon, config, fila, rastreio, supabase, telegram

CHAVE_LISTA = "cupons_agendados"
CHAVE_PROXIMO = "cupom_proximo"
RE_PASSO = re.compile(r"^\s*(\d{1,2})\s*[.)\-–:]\s*(.+)$")
RE_HORA = re.compile(r"(?:(\d{1,2})/(\d{1,2})\s+)?(\d{1,2})[:h](\d{2})?", re.I)

PASSOS_PADRAO = ["Toque no link e adicione os produtos ao carrinho",
                 "Na finalização, toque em \"Cupom\" e cole o código",
                 "Confira o desconto antes de pagar"]


def _campo(linhas: list[str], *nomes: str) -> str:
    for l in linhas:
        if ":" in l:
            chave, valor = l.split(":", 1)
            if chave.strip().lower() in nomes:
                return valor.strip()
    return ""


def _quando(texto: str) -> datetime | None:
    """'00:00' → próxima meia-noite · '25/10 18:30' → esse dia e hora."""
    m = RE_HORA.search(texto or "")
    if not m:
        return None
    agora = datetime.now(fila.FUSO)
    dia, mes, hora, minuto = m.group(1), m.group(2), int(m.group(3)), int(m.group(4) or 0)
    if hora > 23 or minuto > 59:
        return None
    if dia and mes:
        alvo = agora.replace(month=int(mes), day=int(dia), hour=hora, minute=minuto, second=0, microsecond=0)
        if alvo < agora - timedelta(days=1):
            alvo = alvo.replace(year=alvo.year + 1)
        return alvo
    alvo = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=1)


def montar(texto: str) -> dict | None:
    """Lê a mensagem /cupom e devolve {'html', 'codigo', 'quando', 'tem_validade'} (None = formato errado)."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    primeira = linhas[0].split(None, 2) if linhas else []
    if len(primeira) < 2:
        return None
    codigo = primeira[1].upper()
    descricao = primeira[2] if len(primeira) > 2 else ""
    resto = linhas[1:]
    link = next((m.group(0).rstrip(").,") for l in resto for m in [fila.RE_LINK.search(l)] if m), "")
    if not link:
        m = fila.RE_LINK.search(linhas[0])
        if m:
            link = m.group(0).rstrip(").,")
            descricao = descricao.replace(link, "").strip()
    if link and amazon.e_amazon(link):
        novo, _ = amazon.link_com_minha_tag(link)
        link = novo or link
    loja = _campo(resto, "loja")
    validade = _campo(resto, "validade", "valido", "válido", "ate", "até", "vence")
    quando = _quando(_campo(resto, "hora", "horario", "horário", "postar", "agendar"))
    passos = [m.group(2).strip() for l in resto for m in [RE_PASSO.match(l)] if m and not fila.RE_LINK.search(l)]

    partes = [f"🎟️ <b>CUPOM{(' ' + escape(loja.upper())) if loja else ''}</b>", ""]
    partes.append(f"<code>{escape(codigo)}</code>" + (f" — {escape(descricao)}" if descricao else ""))
    if validade:
        partes.append(f"⏰ Válido até {escape(validade)} (ou enquanto durar)")
    partes += ["", "<b>Como usar:</b>"]
    partes += [f"{i}. {escape(p)}" for i, p in enumerate(passos or PASSOS_PADRAO, 1)]
    if link:
        url = rastreio.link(link, None, f"Cupom {codigo}")
        partes += ["", f'🛒 <a href="{escape(url)}">Ir para a {escape(loja or "loja")}</a>']
    partes += ["", "<i>Toque no código para copiar. Regras da loja; o cupom pode acabar antes do prazo.</i>",
               "<i>(ANÚNCIO) #publi · link de afiliado"
               + (f"\n{escape(amazon.AVISO)}" if link and amazon.e_amazon(link) else "") + "</i>"]
    return {"html": "\n".join(partes), "codigo": codigo, "quando": quando, "tem_validade": bool(validade)}


def _lista() -> list[dict]:
    try:
        return json.loads((supabase.ler_config(CHAVE_LISTA) or {}).get("valor") or "[]")
    except ValueError:
        return []


def _gravar(lista: list[dict]) -> None:
    lista.sort(key=lambda c: c["ts"])
    supabase.gravar_config(CHAVE_LISTA, json.dumps(lista, ensure_ascii=False))
    supabase.gravar_config(CHAVE_PROXIMO, str(lista[0]["ts"]) if lista else "")


def agendar(cupom: dict) -> None:
    lista = _lista()
    lista.append({"ts": int(cupom["quando"].timestamp()), "codigo": cupom["codigo"], "html": cupom["html"]})
    _gravar(lista)


def agendados() -> list[dict]:
    return _lista() if supabase.ativo() else []


def cancelar(codigo: str) -> int:
    lista = _lista()
    nova = [c for c in lista if c["codigo"] != codigo.upper()]
    if len(nova) != len(lista):
        _gravar(nova)
    return len(lista) - len(nova)


def postar_se_for_hora(avisar) -> int:
    """Posta os cupons cujo horário chegou (até 2 h de atraso; depois disso descarta e avisa)."""
    if not (supabase.ativo() and config.CANAL_ID):
        return 0
    valor = str((supabase.ler_config(CHAVE_PROXIMO) or {}).get("valor") or "")
    agora = datetime.now(fila.FUSO).timestamp()
    if not valor.isdigit() or agora < int(valor):
        return 0
    lista, feitos, restantes = _lista(), 0, []
    for c in lista:
        if c["ts"] > agora:
            restantes.append(c)
        elif agora - c["ts"] > 2 * 3600:
            avisar(f"⚠️ O cupom {c['codigo']} era para sair às "
                   f"{datetime.fromtimestamp(c['ts'], fila.FUSO):%d/%m %H:%M} e passou do horário — não postei.")
        else:
            try:
                telegram.enviar_html(config.CANAL_ID, c["html"])
                feitos += 1
                avisar(f"✅ Cupom {c['codigo']} publicado no canal (horário marcado).")
            except Exception as erro:  # noqa: BLE001
                avisar(f"❌ Cupom {c['codigo']}: {str(erro)[:150]}")
    _gravar(restantes)
    return feitos
