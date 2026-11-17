from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

STYLES = {
    "educational": "Clear, curious explainer. One idea, simple words, a surprising-but-true hook.",
    "tech_explainer": "Technology/AI explainer. Concrete, no hype, no unverifiable benchmarks.",
    "cinematic_story": "Short emotional story told in images. Show, don't lecture. A small turn at the end.",
    "motivational": "Grounded motivation. Specific and human, no empty slogans or fake testimonials.",
    "comedy": "Light, observational humour. No stereotypes, no real people, no insults.",
    "product_ad_fictional": ("Demonstration advertisement for a FICTIONAL or unnamed product. "
                             "No performance numbers, no benefits that cannot be seen, no testimonials."),
    "typography_quote": "Minimal kinetic-typography piece around one idea. Very short lines.",
    "festival": "Seasonal/festival greeting. Warm and respectful; no invented customs or facts.",
}
MUSIC_MOODS = ("calm", "uplifting", "cinematic", "playful", "tense")
MIN_DURATION, MAX_DURATION = 10, 120


@dataclass
class Settings:
    gemini_api_key: str = ""
    gemini_models: tuple = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
    output_root: Path = Path("output")
    data_dir: Path = Path("docs/data")
    cache_dir: Path = Path("cache")
    music_dir: Path = Path("assets/music")
    tts_engine: str = "auto"                 # auto | piper | espeak
    piper_voice: str = "en_US-lessac-medium"
    voices_dir: Path = Path("cache/voices")
    width: int = 1080
    height: int = 1920
    fps: int = 30
    transition_seconds: float = 0.4
    publish_time_note: str = "19:00 local time (default; no analytics data yet)"
    secrets: list = field(default_factory=list, repr=False)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        models = tuple(m.strip() for m in env.get("GEMINI_MODELS", "").split(",") if m.strip())
        s = cls(
            gemini_api_key=(env.get("GEMINI_API_KEY") or "").strip(),
            output_root=Path(env.get("AUTOREEL_OUTPUT", "output")),
            data_dir=Path(env.get("AUTOREEL_DATA", "docs/data")),
            cache_dir=Path(env.get("AUTOREEL_CACHE", "cache")),
            music_dir=Path(env.get("AUTOREEL_MUSIC_DIR", "assets/music")),
            tts_engine=env.get("TTS_ENGINE", "auto").strip().lower(),
            piper_voice=env.get("PIPER_VOICE", "en_US-lessac-medium").strip(),
        )
        if models:
            s.gemini_models = models
        s.voices_dir = s.cache_dir / "voices"
        s.secrets = [v for k in ("GEMINI_API_KEY", "PIXABAY_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")
                     if (v := env.get(k))]
        return s
