"""FFmpeg assembly: per-scene clips -> cross-faded 9:16 video + ducked music + captions."""
from __future__ import annotations

import logging
from pathlib import Path

from .captions import build_ass, title_ass
from .util import PipelineError, run

log = logging.getLogger("autoreel.editor")
LEAD = 0.35      # silence before narration in each scene
TAIL = 0.45      # silence after narration


def scene_duration(audio_dur: float, transition: float) -> float:
    return max(audio_dur + LEAD + TAIL, 2 * transition + 0.5)


def timeline(durations: list, transition: float) -> list:
    """Global start time of each scene when neighbours overlap by `transition`."""
    starts, t = [], 0.0
    for d in durations:
        starts.append(t)
        t += d - transition
    return starts


def total_length(durations: list, transition: float) -> float:
    return sum(durations) - transition * (len(durations) - 1)


def _enc(settings, preset="veryfast", crf="19"):
    return ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p",
            "-r", str(settings.fps), "-an"]


def render_scene(visual: dict, duration: float, out_path, settings) -> str:
    W, H, fps = settings.width, settings.height, settings.fps
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    kind = visual["type"]
    if kind == "video":
        cmd = base + ["-stream_loop", "-1", "-i", visual["path"], "-t", f"{duration:.3f}",
                      "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                             f"setsar=1,fps={fps},format=yuv420p"]
    elif kind == "image":
        frames = max(1, int(round(duration * fps)))
        zoom = (f"scale={int(W*1.5)}:{int(H*1.5)}:force_original_aspect_ratio=increase,"
                f"crop={int(W*1.5)}:{int(H*1.5)},"
                f"zoompan=z='1+0.10*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={W}x{H}:fps={fps},setsar=1,format=yuv420p")
        cmd = base + ["-loop", "1", "-framerate", str(fps), "-i", visual["path"],
                      "-t", f"{duration:.3f}", "-vf", zoom]
    else:   # typography card background
        cmd = base + ["-f", "lavfi", "-i", f"color=c={visual['color']}:s={W}x{H}:r={fps}",
                      "-t", f"{duration:.3f}", "-vf", "vignette=PI/3.5,format=yuv420p"]
    run(cmd + _enc(settings) + [str(out_path)], timeout=600)
    return str(out_path)


def assemble(scene_files: list, narr_files: list, durations: list, scene_info: list,
             music_path: str, work_dir, out_path, settings, disclaimer: str = "") -> dict:
    """scene_info: [{narration, audio_dur, text_scene, kicker}] aligned with scene_files."""
    T, n = settings.transition_seconds, len(scene_files)
    if n < 2:
        raise PipelineError("At least two scenes are required.")
    starts = timeline(durations, T)
    total = total_length(durations, T)
    events = []
    for i, info in enumerate(scene_info):
        events.append({"start": starts[i], "dur": durations[i], "audio_start": starts[i] + LEAD,
                       "audio_dur": info["audio_dur"], "narration": info["narration"],
                       "text_scene": info["text_scene"], "kicker": info.get("kicker", "")})
    ass_text, srt_text, n_events = build_ass(settings.width, settings.height, events, total, disclaimer)
    work = Path(work_dir)
    (work / "captions.ass").write_text(ass_text, encoding="utf-8")
    (work / "captions.srt").write_text(srt_text, encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for f in scene_files:
        cmd += ["-i", str(Path(f).resolve())]
    for f in narr_files:
        cmd += ["-i", str(Path(f).resolve())]
    cmd += ["-stream_loop", "-1", "-i", str(Path(music_path).resolve())]
    music_idx, narr0 = 2 * n, n

    v = "[0:v]"
    parts = []
    for k in range(1, n):
        parts.append(f"{v}[{k}:v]xfade=transition=fade:duration={T}:offset={starts[k]:.3f}[x{k}]")
        v = f"[x{k}]"
    parts.append(f"{v}ass=captions.ass[vout]")

    for i in range(n):
        ms = int((starts[i] + LEAD) * 1000)
        parts.append(f"[{narr0 + i}:a]aresample=44100,aformat=channel_layouts=stereo,"
                     f"adelay={ms}|{ms}[n{i}]")
    mix_in = "".join(f"[n{i}]" for i in range(n))
    parts.append(f"{mix_in}amix=inputs={n}:normalize=0,apad=whole_dur={total:.3f},asplit=2[narr1][narr2]")
    parts.append(f"[{music_idx}:a]aresample=44100,aformat=channel_layouts=stereo,volume=0.55,"
                 f"atrim=0:{total:.3f},afade=t=in:d=1.5,afade=t=out:st={max(0.0, total-2.5):.3f}:d=2.5[mus]")
    parts.append("[mus][narr1]sidechaincompress=threshold=0.04:ratio=9:attack=30:release=500[duck]")
    parts.append("[narr2][duck]amix=inputs=2:normalize=0,"
                 "loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95[aout]")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(settings.fps),
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart",
            str(Path(out_path).resolve())]
    run(cmd, timeout=1800, cwd=work)
    return {"duration": total, "caption_events": n_events, "starts": starts}


def make_thumbnail(frame_source: str, title: str, work_dir, out_path, settings, at: float = 0.8) -> str:
    work = Path(work_dir)
    (work / "thumb.ass").write_text(title_ass(settings.width, settings.height, title), encoding="utf-8")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at}", "-i",
         str(Path(frame_source).resolve()), "-vf",
         "eq=brightness=-0.12:saturation=1.1,ass=thumb.ass", "-frames:v", "1", "-q:v", "3",
         str(Path(out_path).resolve())], cwd=work)
    return str(out_path)
