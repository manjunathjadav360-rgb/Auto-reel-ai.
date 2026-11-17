"""Orchestrator: runs every stage, records a log, saves the project (even on failure)."""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
import os
import shutil
import time
from pathlib import Path

from src.media import credits_short, credits_text
from src.media.base import unique_assets

from . import captions, editor, qa, store
from .config import Settings
from .music import choose_music
from .scriptgen import generate_script, validate_request
from .tts import clean_text
from .util import PipelineError, media_duration, redact, slugify, write_json
from .visuals import resolve_visuals

log = logging.getLogger("autoreel.pipeline")


class StageLog:
    def __init__(self, secrets):
        self.entries, self.secrets = [], secrets

    @contextlib.contextmanager
    def stage(self, name: str):
        t0 = time.time()
        log.info("== %s", name)
        try:
            yield
        except Exception as exc:
            msg = redact(str(exc) or type(exc).__name__, self.secrets)
            self.entries.append({"stage": name, "ok": False, "seconds": round(time.time() - t0, 1), "message": msg})
            raise
        self.entries.append({"stage": name, "ok": True, "seconds": round(time.time() - t0, 1), "message": ""})

    def note(self, name: str, message: str):
        self.entries.append({"stage": name, "ok": True, "seconds": 0, "message": message})


def new_project_id(topic: str, now: dt.datetime) -> str:
    return f"{now:%Y%m%d-%H%M%S}-{slugify(topic, 28)}"


def generate_project(settings: Settings, topic: str, duration: int, style: str, *,
                     gemini, media, tts, now: dt.datetime = None, repo: str = "") -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    topic, duration, style = validate_request(topic, duration, style)
    pid = new_project_id(topic, now)
    out_dir = Path(settings.output_root) / pid
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    slog = StageLog(settings.secrets)
    project = {"id": pid, "created_at": store.now_iso(now), "status": "running", "topic": topic,
               "style": style, "duration_target": duration, "title": "", "error": None,
               "approval": {"decision": None, "at": None, "note": ""}, "log": slog.entries}
    try:
        with slog.stage("script"):
            script = generate_script(gemini, topic, duration, style)
        project["title"] = script["title"]
        write_json(out_dir / "script.json", script)

        scenes = script["scenes"]
        T = settings.transition_seconds
        with slog.stage("narration"):
            narr_files, audio_durs = [], []
            for i, sc in enumerate(scenes):
                wav = work / f"narr_{i}.wav"
                tts.synthesize(clean_text(sc["narration"]), wav)
                d = media_duration(wav)
                if d < 0.3:
                    raise PipelineError(f"Narration for scene {i + 1} is empty.")
                narr_files.append(str(wav)); audio_durs.append(d)
        durations = [editor.scene_duration(d, T) for d in audio_durs]
        total = editor.total_length(durations, T)

        with slog.stage("visuals"):
            visuals = resolve_visuals(media, scenes, durations, work, style, seed=sum(map(ord, topic)), gemini=gemini)
            if media is None:
                slog.note("visuals", "No media provider configured; all scenes are typography cards.")
            elif media.issues:
                slog.note("visuals", f"{len(media.issues)} media provider issue(s): " +
                          "; ".join(f"{i['provider']}:{i['error']}" for i in media.issues[:3]))

        with slog.stage("music"):
            music_path, music_info = choose_music(settings, script["music_mood"], total, work)

        with slog.stage("render scenes"):
            scene_files = [editor.render_scene(v, d, work / f"scene_{i}.mp4", settings)
                           for i, (v, d) in enumerate(zip(visuals, durations))]

        with slog.stage("assemble"):
            info = [{"narration": sc["narration"], "audio_dur": ad, "text_scene": v["type"] == "text",
                     "kicker": sc["on_screen_text"]} for sc, ad, v in zip(scenes, audio_durs, visuals)]
            final = out_dir / "final.mp4"
            res = editor.assemble(scene_files, narr_files, durations, info, music_path, work, final,
                                  settings, script.get("disclaimer", ""))
            shutil.copy(work / "captions.srt", out_dir / "captions.srt")

        with slog.stage("thumbnail"):
            editor.make_thumbnail(scene_files[0], script["title"], work, out_dir / "thumbnail.jpg", settings)

        with slog.stage("quality check"):
            report = qa.run_qa(final, target_duration=duration, visuals=visuals,
                               caption_events=res["caption_events"],
                               claims_to_verify=script["claims_to_verify"],
                               width=settings.width, height=settings.height)

        used = unique_assets(v["asset"] for v in visuals if v["asset"])
        credit_line = credits_short(used)
        caption = script["caption"]
        if script.get("disclaimer"):
            caption += f"\n\n{script['disclaimer']}"
        if credit_line:
            caption += f"\n\n{credit_line}"
        tag = f"project-{pid}"
        base = f"https://github.com/{repo}/releases/download/{tag}" if repo else f"output/{pid}"
        project.update({
            "status": "qa_failed" if report["status"] == "fail" else "needs_review",
            "title": script["title"], "script": script,
            "scene_visuals": [{"type": v["type"], "query": v.get("query", ""),
                               "asset": ({k: v["asset"].to_dict()[k] for k in
                                          ("provider", "asset_id", "kind", "page_url", "creator", "creator_url",
                                           "width", "height", "duration", "license_name")} if v["asset"] else None)}
                              for v in visuals],
            "narration": {"engine": tts.name, "voice": getattr(tts, "voice", ""), "license_note": tts.license_note},
            "music": music_info, "qa": report,
            "assets": {"tag": tag, "video_url": f"{base}/final.mp4", "thumbnail_url": f"{base}/thumbnail.jpg",
                       "captions_url": f"{base}/captions.srt", "duration": round(total, 2)},
            "credits": credits_text(used),
            "publish": {"caption": caption, "hashtags": script["hashtags"],
                        "suggested_time": settings.publish_time_note,
                        "note": "Manual posting only. Nothing is published automatically."},
        })
    except Exception as exc:            # noqa: BLE001 - recorded, then re-raised
        project["status"] = "failed"
        project["error"] = redact(str(exc) or type(exc).__name__, settings.secrets)
        log.error("Project %s failed: %s", pid, project["error"])
        store.save_project(settings.data_dir, project)
        raise
    finally:
        if not os.environ.get("AUTOREEL_KEEP_WORK"):
            shutil.rmtree(work, ignore_errors=True)
    write_json(out_dir / "project.json", project)
    store.save_project(settings.data_dir, project)
    return project
