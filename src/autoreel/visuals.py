"""Pick a visual for every scene: Pixabay video -> Pixabay image -> typography card."""
from __future__ import annotations

import logging
from pathlib import Path

from src.media import MediaError

from .util import probe

log = logging.getLogger("autoreel.visuals")
PALETTES = ["0x14213d", "0x1b2a41", "0x2d1e2f", "0x0b3c49", "0x3a2e39", "0x22333b"]


def _valid_video(path) -> bool:
    try:
        streams = probe(path).get("streams", [])
        return any(s.get("codec_type") == "video" and s.get("width") for s in streams)
    except Exception:
        return False


def resolve_visuals(media, scenes: list, durations: list, work_dir, style: str, seed: int = 0, gemini=None) -> list:
    """Return one dict per scene: {type, path, asset, query, color, style}."""
    if style == "anime_story":
        if gemini is None:
            raise RuntimeError("Anime story mode needs the Gemini image generator.")
        from .anime import generate_anime_scenes
        results = generate_anime_scenes(gemini, scenes, work_dir)
        for item in results:
            item["style"] = style
        return results
    assets_dir = Path(work_dir) / "media"
    used, out = set(), []
    force_text = style == "typography_quote"
    for i, (scene, dur) in enumerate(zip(scenes, durations)):
        color = PALETTES[(seed + i) % len(PALETTES)]
        chosen = {"type": "text", "path": None, "asset": None, "query": "", "color": color}
        if media is not None and not force_text:
            for query in dict.fromkeys([scene["search_query"], scene["fallback_query"]]):
                chosen = _try_video(media, query, dur, assets_dir, used) or \
                         _try_image(media, query, assets_dir, used) or chosen
                if chosen["type"] != "text":
                    break
        chosen["color"] = color
        chosen["style"] = style
        log.info("scene %d -> %s (%s)", i + 1, chosen["type"], chosen.get("query") or "no query")
        out.append(chosen)
    return out


def _try_video(media, query, dur, assets_dir, used):
    found = media.search_videos(query, orientation="prefer_vertical",
                                min_duration=min(dur, 6.0), limit=8)
    for asset in found:
        key = (asset.provider, asset.asset_id)
        if key in used:
            continue
        try:
            asset = media.download(asset, assets_dir)
        except MediaError as exc:
            log.warning("download failed for %s: %s", asset.asset_id, exc)
            media.issues.append({"provider": asset.provider, "query": query,
                                 "error": type(exc).__name__, "detail": str(exc)})
            continue
        if _valid_video(asset.local_path):
            used.add(key)
            return {"type": "video", "path": asset.local_path, "asset": asset, "query": query}
    return None


def _try_image(media, query, assets_dir, used):
    for asset in media.search_images(query, orientation="prefer_vertical", limit=6):
        key = (asset.provider, asset.asset_id)
        if key in used:
            continue
        try:
            asset = media.download(asset, assets_dir)
        except MediaError as exc:
            log.warning("image download failed for %s: %s", asset.asset_id, exc)
            continue
        used.add(key)
        return {"type": "image", "path": asset.local_path, "asset": asset, "query": query}
    return None
