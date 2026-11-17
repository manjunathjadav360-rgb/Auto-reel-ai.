"""Gemini-generated anime illustrations with FFmpeg camera motion.
This creates a motion-comic from illustrated frames, not frame-by-frame character animation.
"""
from __future__ import annotations
import logging
from pathlib import Path
from .util import PipelineError

log = logging.getLogger("autoreel.anime")
CHARACTERS = (
    "Maintain consistent original adult Indian college-age characters: Aarav, 21, "
    "wavy black hair, warm brown eyes, navy-blue overshirt and silver watch; Meera, 21, "
    "long dark hair, expressive brown eyes, muted rose kurta and tiny crescent hair clip. "
    "Hand-drawn 2D anime feature-film aesthetic, expressive faces, delicate line art, "
    "painterly backgrounds, natural Indian campus and city details, cinematic lighting, "
    "restrained colors, vertical 9:16 composition. No text, captions, logos, watermark, "
    "photorealism, or existing copyrighted characters."
)

def generate_anime_scenes(gemini, scenes: list, work_dir) -> list:
    folder = Path(work_dir) / "anime"
    folder.mkdir(parents=True, exist_ok=True)
    visuals = []
    for index, scene in enumerate(scenes, 1):
        prompt = (
            "Generate one finished vertical 9:16 2D anime illustration for this moment "
            "in an original Hindi romantic short film. " + CHARACTERS +
            f" Scene {index}: {scene.get('narration', '')}. "
            f"Visual direction: {scene.get('search_query', '')}. "
            "Show one readable moment with expressive body language and cinematic depth. "
            "Do not include written words."
        )
        try:
            data = gemini.generate_image(prompt)
        except Exception as exc:
            raise PipelineError(
                f"Anime illustration generation failed on scene {index}: {type(exc).__name__}. "
                "Check Gemini image-model access/quota and retry."
            ) from None
        path = folder / f"anime_scene_{index:02d}.jpg"
        path.write_bytes(data)
        visuals.append({"type": "image", "path": str(path), "asset": None,
                        "query": "AI-generated original 2D anime illustration", "color": "0x241b2f"})
        log.info("Generated anime illustration %d/%d", index, len(scenes))
    return visuals
