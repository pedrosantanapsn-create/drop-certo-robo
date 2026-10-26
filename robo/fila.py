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
PREFIXO_FOTO = "fila_foto_"          # ofertas com foto (uma linha cada)

INTERVALO_MIN = timedelta(minutes=30)
INTERVALO_MAX = timedelta(hours=3)
DISTANCIA_PICO = timedelta(minutes=55)   # espaço mínimo entre posts no modo pico
RE_LINK = re.compile(r"(https?://\S+|\bmeli\.la/\S+|\bmercadolivre\.com\.br/\S+)", re.I)


# ---------------------------------------------------------------------------
# Leitura e gravação
# ---------------------------------------------------------------------------
def ativa() -> bool:
    return supabase.ativo()


def _itens_texto() -> list[dict]:
    linha = supabase.ler_config(CHAVE_FILA)
    if not linha:
        return []
    try:
        dados = json.loads(linha.get("valor") or "[]")
        return dados if isinstance(dados, list) else []
    except ValueError:
        return []


def _linhas_foto() -> list[dict]:
    lista = []
    for linha in supabase.listar_config(PREFIXO_FOTO):
        try:
            item = json.loads(linha.get("valor") or "{}")
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("foto_id"):
            item["_chave"] = linha["chave"]
            lista.append(item)
    return lista


def _itens_foto(incluir_sem_link: bool = False) -> list[dict]:
    """Ofertas com foto: cada foto numa linha própria da tabela config
    (fila_foto_...), para várias fotos chegando juntas não se atropelarem.

    Álbum (várias fotos de uma vez): cada foto pode ter o seu link na legenda,
    ou UMA legenda com todos os links, um por linha, na mesma ordem das fotos.
    """
    linhas = _linhas_foto()
    grupos: dict[str, list[dict]] = {}
    prontos = []
    for item in linhas:
        if item.get("grupo"):
            grupos.setdefault(item["grupo"], []).append(item)
        elif item.get("texto"):
            prontos.append(item)
    for fotos in grupos.values():
        fotos.sort(key=lambda i: i.get("msg", 0))
        ofertas = [o for i in fotos for o in separar_ofertas(i.get("texto", ""))]
        if len(ofertas) == len(fotos) and any(len(separar_ofertas(i.get("texto", ""))) > 1 for i in fotos):
            for foto, oferta in zip(fotos, ofertas):     # legenda única com todos os links
                prontos.append({**foto, "texto": oferta})
        else:
            for foto in fotos:                            # cada foto com o seu link
                if len(separar_ofertas(foto.get("texto", ""))) == 1 or incluir_sem_link:
                    prontos.append(foto)
    return prontos


def fotos_sem_link() -> int:
    com_link = {i["_chave"] for i in _itens_foto()}
    return sum(1 for i in _linhas_foto() if i["_chave"] not in com_link)


def itens() -> list[dict]:
    """Fila completa, na ordem em que as ofertas chegaram."""
    return sorted(_itens_texto() + _itens_foto(), key=lambda i: (str(i.get("adicionado", "")), i.get("msg", 0)))


def _salvar(lista: list[dict]) -> None:
    so_texto = [i for i in lista if "_chave" not in i]
    supabase.gravar_config(CHAVE_FILA, json.dumps(so_texto, ensure_ascii=False))


def _proxima() -> datetime | None:
    linha = supabase.ler_config(CHAVE_PROXIMA)
    valor = (linha or {}).get("valor", "")
    return datetime.fromtimestamp(int(valor), FUSO) if str(valor).isdigit() else None


def _marcar_proxima(quando: datetime | None) -> None:
    supabase.gravar_config(CHAVE_PROXIMA, str(int(quando.timestamp())) if quando else "")


def modo() -> str:
    """Como a fila é distribuída:
    "hora"  (padrão) 1 post a cada MINUTOS_FORA_PICO (30 min); no pico, a cada MINUTOS_NO_PICO (20 min)
    "pico"  só os melhores horários do dia, com ~1 h entre posts
    "igual" espalha por igual no dia
    "fixo"  intervalo em minutos definido com /intervalo N"""
    valor = str((supabase.ler_config(CHAVE_INTERVALO) or {}).get("valor", "")).strip()
    if valor.isdigit() and int(valor) > 0:
        return "fixo"
    return valor if valor in ("igual", "pico") else "hora"


def definir_modo(nome: str) -> None:
    supabase.gravar_config(CHAVE_INTERVALO, nome if nome in ("igual", "pico") else "")


def _janelas_pico(dia: datetime) -> list[tuple[datetime, datetime]]:
    janelas = []
    for trecho in config.HORARIOS_PICO.split(","):
        try:
            ini, fim = (datetime.strptime(x.strip(), "%H:%M") for x in trecho.split("-"))
        except ValueError:
            continue
        janelas.append((dia.replace(hour=ini.hour, minute=ini.minute, second=0, microsecond=0),
                        dia.replace(hour=fim.hour, minute=fim.minute, second=0, microsecond=0)))
    return janelas


def em_pico(quando: datetime) -> bool:
    return any(ini <= quando < fim for ini, fim in _janelas_pico(quando))


def proximo_hora(agora: datetime) -> datetime:
    """Modo "hora": +20 min dentro do pico, +1 h fora dele (adiantando se um pico
    começar antes disso)."""
    if em_pico(agora):
        return _dentro_da_janela(agora + timedelta(minutes=config.MINUTOS_NO_PICO))
    alvo = agora + timedelta(minutes=config.MINUTOS_FORA_PICO)
    minimo = agora + timedelta(minutes=config.MINUTOS_NO_PICO)
    for ini, _fim in _janelas_pico(agora):
        if agora < ini < alvo:
            alvo = max(ini, minimo)       # o pico começa antes: adianta o próximo post
    return _dentro_da_janela(alvo)


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


# Horários de mais movimento nas redes no Brasil (almoço e noite valem mais).
# Peso maior = horário preferido. Os posts vão para os melhores horários que
# ainda restam no dia; se sobrar oferta, ocupam também os horários comuns.
def _peso(h: float) -> int:
    if 19 <= h < 21.5:
        return 5          # noite: pico principal
    if 18 <= h < 19 or 21.5 <= h < 22.5:
        return 4
    if 11.5 <= h < 13.5:
        return 4          # almoço
    if 7.5 <= h < 9:
        return 3          # começo do dia (ônibus, metrô)
    if 17 <= h < 18:
        return 2
    return 1


def _horarios_do_dia(dia: datetime) -> list[datetime]:
    """Horários possíveis (de 30 em 30 min) dentro do período de postagem."""
    inicio, fim = _janela(dia)
    lista, h = [], inicio
    while h < fim:
        lista.append(h)
        h += timedelta(minutes=30)
    return lista


def plano_pico(agora: datetime, pendentes: int, folga: timedelta = INTERVALO_MIN) -> datetime:
    """Melhor horário para o próximo post, escolhendo os horários de pico."""
    dia = agora
    for _ in range(8):
        livres = [h for h in _horarios_do_dia(dia) if h >= agora + folga]
        if livres:
            # Pega os melhores horários, com pelo menos ~1 hora entre um post e outro
            escolhidos: list[datetime] = []
            for h in sorted(livres, key=lambda h: (-_peso(h.hour + h.minute / 60), h)):
                if all(abs(h - e) >= DISTANCIA_PICO for e in escolhidos):
                    escolhidos.append(h)
                if len(escolhidos) >= max(pendentes, 1):
                    break
            return min(escolhidos)
        dia = _amanha_cedo(dia)
        agora, folga = dia, timedelta(0)
    return _dentro_da_janela(agora)


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
        links = RE_LINK.findall(linha)
        if len(links) > 1:
            # vários links na mesma linha (separados por espaço): cada um vira uma oferta
            ofertas.extend([l.rstrip(").,;!?")] for l in links)
        elif links:
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


def adicionar(ofertas: list[str], fotos: list[str | None] | None = None) -> tuple[int, datetime, int]:
    """Coloca as ofertas no fim da fila, sem repetir links.

    Devolve (total na fila, horário do próximo post, quantos repetidos foram ignorados).
    """
    lista = itens()
    agora = datetime.now(FUSO)
    ja_tem = {chave_link(i.get("texto", "")) for i in lista}
    ignorados = 0
    for n, texto in enumerate(ofertas):
        chave = chave_link(texto)
        if chave and chave in ja_tem:
            ignorados += 1
            continue
        ja_tem.add(chave)
        item = {"texto": texto, "adicionado": agora.isoformat(timespec="seconds")}
        if fotos and n < len(fotos) and fotos[n]:
            item["foto_url"] = fotos[n]        # foto enviada pelo quadro do site
        lista.append(item)
    _salvar(lista)
    proxima = _proxima()
    if lista and modo() == "pico":
        plano = plano_pico(agora, len(lista), timedelta(0))
        if proxima is None or proxima < agora or plano < proxima:
            proxima = plano
            _marcar_proxima(proxima)
    elif lista and (proxima is None or proxima < agora):
        proxima = _dentro_da_janela(agora)
        _marcar_proxima(proxima)
    return len(lista), proxima or _dentro_da_janela(agora), ignorados


def adicionar_foto(texto: str, foto_id: str, msg_id: int, grupo: str = "") -> tuple[int, datetime, bool]:
    """Coloca na fila uma oferta mandada como FOTO (link na legenda).

    Devolve (total na fila, horário do próximo post, se era repetida).
    """
    agora = datetime.now(FUSO)
    lista = itens()
    links = separar_ofertas(texto)
    ja_tem = {chave_link(i.get("texto", "")) for i in lista}
    if len(links) == 1 and chave_link(texto) in ja_tem:
        return len(lista), _proxima() or _dentro_da_janela(agora), True
    supabase.gravar_config(f"{PREFIXO_FOTO}{grupo or 'avulsa'}_{int(msg_id):012d}", json.dumps(
        {"texto": texto, "foto_id": foto_id, "grupo": grupo, "msg": int(msg_id),
         "adicionado": agora.isoformat(timespec="seconds")}, ensure_ascii=False))
    total = len(itens())
    proxima = _proxima()
    if total and modo() == "pico":
        plano = plano_pico(agora, total, timedelta(0))
        if proxima is None or proxima < agora or plano < proxima:
            proxima = plano
            _marcar_proxima(proxima)
    elif total and (proxima is None or proxima < agora):
        proxima = _dentro_da_janela(agora)
        _marcar_proxima(proxima)
    return total, proxima or _dentro_da_janela(agora), False


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
    if "_chave" in item:
        supabase.apagar_config(item["_chave"])
    else:
        _salvar(lista)
    agora = datetime.now(FUSO)
    if lista and modo() == "pico":
        _marcar_proxima(plano_pico(agora, len(lista)))
    elif lista and modo() == "hora":
        _marcar_proxima(proximo_hora(agora))
    elif lista:
        _marcar_proxima(_dentro_da_janela(agora + _passo(agora, len(lista))))
    else:
        _marcar_proxima(None)
    return item


def limpar() -> int:
    total = len(itens())
    for item in _linhas_foto():
        supabase.apagar_config(item["_chave"])
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
    jeito = modo()
    linhas = [f"🗓️ Fila de postagens: {len(lista)} oferta(s)"]
    if proxima:
        linhas.append(f"⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}")
    if jeito == "hora":
        linhas.append(f"⏱️ 1 post a cada {config.MINUTOS_FORA_PICO} min · no pico ({config.HORARIOS_PICO.replace(',', ' e ')}) "
                      f"a cada {config.MINUTOS_NO_PICO} min")
    elif jeito == "fixo":
        linhas.append(f"⏱️ Intervalo: {fixo} min (fixo)")
    elif jeito == "igual":
        linhas.append(f"⏱️ Intervalo: espalhado por igual até as {config.POSTAR_ATE}h")
    else:
        linhas.append("⏱️ Horários de pico: almoço (11h30–13h30) e noite (19h–23h) primeiro")
    linhas.append(f"🕗 Posta das {config.POSTAR_DAS}h às {config.POSTAR_ATE}h\n")
    for i, item in enumerate(lista[:15], 1):
        primeira = item["texto"].splitlines()[0]
        linhas.append(f"{i}. {'📷 ' if item.get('foto_id') or item.get('foto_url') else ''}{primeira[:60]}")
    if len(lista) > 15:
        linhas.append(f"… e mais {len(lista) - 15}")
    orfas = fotos_sem_link()
    if orfas:
        linhas.append(f"\n⚠️ {orfas} foto(s) sem link — mande /limpar e reenvie com o link na legenda.")
    return "\n".join(linhas)
