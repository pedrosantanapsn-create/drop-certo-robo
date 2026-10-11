"""Fila de postagens: você manda vários links de uma vez e o robô posta
um por vez, espalhados ao longo do dia.

Tudo fica guardado na tabela "config" do Supabase (a mesma do token):
  fila           -> lista de ofertas esperando (JSON)
  fila_proxima   -> horário (segundos desde 1970) do próximo post

O GitHub Actions confere "fila_proxima" a cada 10 minutos; quando chega a
hora, o robô roda, posta o primeiro item e marca o horário do seguinte.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, supabase

FUSO = ZoneInfo("America/Sao_Paulo")
CHAVE_FILA = "fila"
CHAVE_PROXIMA = "fila_proxima"
CHAVE_INTERVALO = "fila_intervalo"   # minutos fixos (vazio = automático)

INTERVALO_MIN = timedelta(minutes=30)
INTERVALO_MAX = timedelta(hours=3)
RE_LINK = re.compile(r"(https?://\S+|\bmeli\.la/\S+|\bmercadolivre\.com\.br/\S+)", re.I)


# ---------------------------------------------------------------------------
# Leitura e gravação
# ---------------------------------------------------------------------------
def ativa() -> bool:
    return supabase.ativo()


def itens() -> list[dict]:
    linha = supabase.ler_config(CHAVE_FILA)
    if not linha:
        return []
    try:
        dados = json.loads(linha.get("valor") or "[]")
        return dados if isinstance(dados, list) else []
    except ValueError:
        return []


def _salvar(lista: list[dict]) -> None:
    supabase.gravar_config(CHAVE_FILA, json.dumps(lista, ensure_ascii=False))


def _proxima() -> datetime | None:
    linha = supabase.ler_config(CHAVE_PROXIMA)
    valor = (linha or {}).get("valor", "")
    return datetime.fromtimestamp(int(valor), FUSO) if str(valor).isdigit() else None


def _marcar_proxima(quando: datetime | None) -> None:
    supabase.gravar_config(CHAVE_PROXIMA, str(int(quando.timestamp())) if quando else "")


def intervalo_fixo() -> int | None:
    linha = supabase.ler_config(CHAVE_INTERVALO)
    valor = (linha or {}).get("valor", "")
    return int(valor) if str(valor).isdigit() and int(valor) > 0 else None


def definir_intervalo(minutos: int | None) -> None:
    supabase.gravar_config(CHAVE_INTERVALO, str(minutos) if minutos else "")


# ---------------------------------------------------------------------------
# Horários
# ---------------------------------------------------------------------------
def _janela(dia: datetime) -> tuple[datetime, datetime]:
    inicio = dia.replace(hour=config.POSTAR_DAS, minute=0, second=0, microsecond=0)
    fim = dia.replace(hour=config.POSTAR_ATE, minute=0, second=0, microsecond=0)
    return inicio, fim


def _amanha_cedo(agora: datetime) -> datetime:
    return _janela(agora + timedelta(days=1))[0]


def _dentro_da_janela(quando: datetime) -> datetime:
    """Se o horário cair fora do período de postagem, joga para o início do próximo."""
    inicio, fim = _janela(quando)
    if quando < inicio:
        return inicio
    if quando >= fim:
        return _amanha_cedo(quando)
    return quando


def _passo(agora: datetime, pendentes: int) -> timedelta:
    """Distribui os itens que faltam no tempo que resta do dia."""
    fixo = intervalo_fixo()
    if fixo:
        return timedelta(minutes=fixo)
    inicio, fim = _janela(agora)
    base = max(agora, inicio)
    resta = fim - base if base < fim else (fim - inicio)
    passo = resta / (max(pendentes, 1) + 0.5)   # o último cai antes do fim do dia
    return max(INTERVALO_MIN, min(INTERVALO_MAX, passo))


# ---------------------------------------------------------------------------
# Operações usadas pelo robô
# ---------------------------------------------------------------------------
def separar_ofertas(texto: str) -> list[str]:
    """Quebra a mensagem em ofertas: cada linha com link começa uma oferta;
    linhas sem link logo abaixo (preco:, nome:, obs:) ficam junto dela."""
    ofertas: list[list[str]] = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if RE_LINK.search(linha):
            ofertas.append([linha])
        elif ofertas:
            ofertas[-1].append(linha)
    return ["\n".join(o) for o in ofertas]


def chave_link(texto: str) -> str:
    """Forma "normalizada" do link, para achar repetidos (ignora https, www, / final)."""
    achado = RE_LINK.search(texto or "")
    if not achado:
        return ""
    link = achado.group(1).rstrip(").,;!?")
    link = re.sub(r"^https?://", "", link, flags=re.I)
    link = re.sub(r"^www\.", "", link, flags=re.I)
    dominio, _, caminho = link.partition("/")
    # o domínio não diferencia maiúsculas; o código do link curto diferencia (1AoCm7N ≠ 1aocm7n)
    return f"{dominio.lower()}/{caminho}".rstrip("/")


def adicionar(ofertas: list[str]) -> tuple[int, datetime, int]:
    """Coloca as ofertas no fim da fila, sem repetir links.

    Devolve (total na fila, horário do próximo post, quantos repetidos foram ignorados).
    """
    lista = itens()
    agora = datetime.now(FUSO)
    ja_tem = {chave_link(i.get("texto", "")) for i in lista}
    ignorados = 0
    for texto in ofertas:
        chave = chave_link(texto)
        if chave and chave in ja_tem:
            ignorados += 1
            continue
        ja_tem.add(chave)
        lista.append({"texto": texto, "adicionado": agora.isoformat(timespec="minutes")})
    _salvar(lista)
    proxima = _proxima()
    if lista and (proxima is None or proxima < agora):
        proxima = _dentro_da_janela(agora)
        _marcar_proxima(proxima)
    return len(lista), proxima or _dentro_da_janela(agora), ignorados


def esta_na_hora() -> bool:
    proxima = _proxima()
    return proxima is not None and datetime.now(FUSO) >= proxima


def retirar_proximo() -> dict | None:
    """Tira o primeiro item da fila e já agenda o seguinte."""
    lista = itens()
    if not lista:
        _marcar_proxima(None)
        return None
    item = lista.pop(0)
    _salvar(lista)
    agora = datetime.now(FUSO)
    if lista:
        _marcar_proxima(_dentro_da_janela(agora + _passo(agora, len(lista))))
    else:
        _marcar_proxima(None)
    return item


def limpar() -> int:
    total = len(itens())
    _salvar([])
    _marcar_proxima(None)
    return total


def adiantar() -> None:
    """Comando /agora: o próximo item sai na próxima rodada do robô."""
    if itens():
        _marcar_proxima(datetime.now(FUSO))


def resumo() -> str:
    lista = itens()
    if not lista:
        return "📭 A fila está vazia.\n\nMande vários links numa mensagem (um por linha) para agendar."
    proxima = _proxima()
    fixo = intervalo_fixo()
    linhas = [f"🗓️ Fila de postagens: {len(lista)} oferta(s)"]
    if proxima:
        linhas.append(f"⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}")
    linhas.append(f"⏱️ Intervalo: {f'{fixo} min (fixo)' if fixo else 'automático (espalha até as %dh)' % config.POSTAR_ATE}")
    linhas.append(f"🕗 Posta das {config.POSTAR_DAS}h às {config.POSTAR_ATE}h\n")
    for i, item in enumerate(lista[:15], 1):
        primeira = item["texto"].splitlines()[0]
        linhas.append(f"{i}. {primeira[:60]}")
    if len(lista) > 15:
        linhas.append(f"… e mais {len(lista) - 15}")
    return "\n".join(linhas)
