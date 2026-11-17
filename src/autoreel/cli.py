"""Command line: python -m src.autoreel <doctor|research|generate|set-status>"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from src.media import MediaConfigError, build_manager_from_env

from . import research, store
from .config import STYLES, Settings
from .llm import GeminiClient, GeminiError
from .pipeline import generate_project
from .scriptgen import scene_count
from .tts import EspeakEngine, PiperEngine, pick_engine
from .util import PipelineError, setup_logging

log = logging.getLogger("autoreel.cli")


def cmd_doctor(settings: Settings, args) -> int:
    ok = True

    def line(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"[{'OK' if good else 'MISSING'}] {name} {detail}")

    line("ffmpeg", shutil.which("ffmpeg")); line("ffprobe", shutil.which("ffprobe"))
    line("GEMINI_API_KEY", settings.gemini_api_key, "(set)" if settings.gemini_api_key else "")
    line("PIXABAY_API_KEY", os.environ.get("PIXABAY_API_KEY"), "(set)" if os.environ.get("PIXABAY_API_KEY") else "")
    line("TTS engine", PiperEngine.installed() or EspeakEngine.installed(),
         "piper" if PiperEngine.installed() else ("espeak-ng" if EspeakEngine.installed() else ""))
    fonts = Path("/usr/share/fonts/truetype/dejavu")
    line("DejaVu font (captions)", fonts.exists() or sys.platform != "linux")
    return 0 if ok else 1


def cmd_research(settings: Settings, args) -> int:
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_models)
    result = research.run_research(gemini, args.category, args.count)
    store.save_ideas(settings.data_dir, result)
    print(json.dumps(result["ideas"], indent=2))
    return 0


def cmd_generate(settings: Settings, args) -> int:
    env = dict(os.environ)
    env.setdefault("PIXABAY_MAX_DOWNLOADS", str(scene_count(args.duration) + 4))
    media = None
    if not args.no_media:
        try:
            media = build_manager_from_env(env, settings.cache_dir)
        except MediaConfigError as exc:
            log.warning("Stock media disabled: %s (scenes become typography cards)", exc)
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_models)
    tts = pick_engine(settings)
    project = generate_project(settings, args.topic, args.duration, args.style, gemini=gemini,
                               media=media, tts=tts, repo=os.environ.get("GITHUB_REPOSITORY", ""))
    print(f"PROJECT_ID={project['id']}\nSTATUS={project['status']}\nQA={project['qa']['status']}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"project_id={project['id']}\ntitle_text={project['title'][:100]}\n")
    return 0


def cmd_set_status(settings: Settings, args) -> int:
    project = store.set_status(settings.data_dir, args.id, args.decision, args.note or "")
    print(f"{project['id']} -> {project['status']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autoreel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    r = sub.add_parser("research"); r.add_argument("--category", default="educational", choices=sorted(STYLES)); r.add_argument("--count", type=int, default=6)
    g = sub.add_parser("generate"); g.add_argument("--topic", required=True); g.add_argument("--duration", type=int, default=30)
    g.add_argument("--style", default="educational", choices=sorted(STYLES)); g.add_argument("--no-media", action="store_true")
    s = sub.add_parser("set-status"); s.add_argument("--id", required=True); s.add_argument("--decision", required=True, choices=["approve", "reject"]); s.add_argument("--note", default="")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    setup_logging(settings.secrets)
    handler = {"doctor": cmd_doctor, "research": cmd_research, "generate": cmd_generate, "set-status": cmd_set_status}[args.cmd]
    try:
        return handler(settings, args)
    except (PipelineError, GeminiError) as exc:
        from .util import redact
        print("ERROR: " + redact(str(exc), settings.secrets), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
