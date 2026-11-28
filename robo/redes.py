"""Quais ofertas viram vídeo (Reels/TikTok).

Dados do painel do Instagram (nov/2026): 11 mil visualizações, 4 interações, 0 toques no link — volume alto com
produto repetido e capa com o logotipo da loja derruba a entrega. Então: poucos vídeos, só dos melhores produtos,
sem repetir o mesmo produto na semana e nunca sem a foto real.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, supabase

CHAVE = "videos_feitos"            # {chave do produto: quando teve vídeo}


def logo_de_loja(caminho: Path) -> bool:
    """True se a "foto" é só o logotipo da Shopee (quase tudo que não é branco é o laranja da marca)."""
    try:
        from PIL import Image
        img = Image.open(caminho).convert("RGB").resize((96, 96))
        cor = marca = 0
        for r, g, b in img.getdata():
            if min(r, g, b) > 232:                       # fundo branco
                continue
            cor += 1
            if abs(r - 238) < 34 and abs(g - 77) < 40 and abs(b - 45) < 40:
                marca += 1
        return cor > 200 and marca / cor > 0.72
    except Exception:  # noqa: BLE001
        return False


def fotos_reais(fotos: list[Path]) -> list[Path]:
    return [f for f in fotos if not logo_de_loja(f)]


def _feitos() -> dict:
    try:
        dados = json.loads((supabase.ler_config(CHAVE) or {}).get("valor") or "{}")
        return dados if isinstance(dados, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _chave(nome: str) -> str:
    from . import canais
    return canais._chave_produto(nome)


def teve_video(nome: str) -> bool:
    """O mesmo produto já virou vídeo nos últimos VIDEO_REPETIR_DIAS?"""
    if not (supabase.ativo() and config.VIDEO_REPETIR_DIAS and nome):
        return False
    return time.time() - float(_feitos().get(_chave(nome), 0)) < config.VIDEO_REPETIR_DIAS * 86400


def marcar(nome: str) -> None:
    if not (supabase.ativo() and nome):
        return
    feitos = _feitos()
    feitos[_chave(nome)] = int(time.time())
    recentes = dict(sorted(feitos.items(), key=lambda kv: kv[1])[-400:])
    supabase.gravar_config(CHAVE, json.dumps(recentes))


def _vaga(rede: str, maximo: int, intervalo_h: float) -> bool:
    from . import relatorio
    if not maximo or not supabase.ativo():
        return True
    return (relatorio.postados_hoje(rede) < maximo
            and time.time() - relatorio.ultimo_post(rede) >= intervalo_h * 3600)


def vale_video(produto, fotos: list[Path], nota: int) -> tuple[bool, str]:
    """(faz o vídeo?, motivo quando não faz)."""
    from . import instagram, roteiros, tiktok
    if not fotos:
        return False, "sem foto real do produto"
    if teve_video(produto.nome):
        return False, f"esse produto já teve vídeo nos últimos {config.VIDEO_REPETIR_DIAS} dias"
    pontos, _ = roteiros._pontuar(produto.nome or "", produto.preco, produto.preco_antigo, True, nota)
    if pontos < config.VIDEO_PONTOS_MINIMOS:
        return False, f"{pontos} pontos para vídeo (mínimo {config.VIDEO_PONTOS_MINIMOS}): fica no canal e no site"
    try:
        vagas = [(instagram.ativo(), "instagram", config.INSTAGRAM_MAX_DIA, config.INSTAGRAM_INTERVALO_H),
                 (tiktok.ativo(), "tiktok", config.TIKTOK_MAX_DIA, config.TIKTOK_INTERVALO_H)]
        ligadas = [v for v in vagas if v[0]]
        if ligadas and not any(_vaga(r, m, h) for _, r, m, h in ligadas):
            return False, "sem vaga de vídeo agora (limite do dia ou intervalo entre vídeos)"
    except Exception:  # noqa: BLE001
        pass
    return True, f"{pontos} pontos para vídeo"
