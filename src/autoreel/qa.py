"""Quality assurance: objective checks on the exported file. It cannot judge taste."""
from __future__ import annotations

import re
from pathlib import Path

from .util import PipelineError, probe, run

ORDER = {"pass": 0, "warn": 1, "fail": 2}


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def analyse_media(path) -> dict:
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect",
                "-vf", "blackdetect=d=0.4:pic_th=0.97", "-f", "null", "-"], timeout=600)
    err = proc.stderr
    mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", err)
    peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", err)
    black = sum(float(m) for m in re.findall(r"black_duration:([\d.]+)", err))
    num = lambda m: (float(m.group(1)) if m and m.group(1) != "-inf" else -91.0)
    return {"mean_volume": num(mean), "max_volume": num(peak), "black_seconds": black}


def run_qa(video_path, *, target_duration: int, visuals: list, caption_events: int,
           claims_to_verify: list, width=1080, height=1920) -> dict:
    checks = []
    path = Path(video_path)
    if not path.exists() or path.stat().st_size < 10_000:
        return {"status": "fail", "checks": [_check("file", "fail", "video file missing or empty")]}
    info = probe(path)
    vs = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    size_mb = path.stat().st_size / 1e6

    ok = vs and vs["codec_name"] == "h264" and vs.get("pix_fmt") == "yuv420p"
    checks.append(_check("codec", "pass" if ok else "fail", f"{vs and vs['codec_name']}/{vs and vs.get('pix_fmt')}"))
    right = vs and (vs["width"], vs["height"]) == (width, height)
    checks.append(_check("resolution", "pass" if right else "fail",
                         f"{vs and vs['width']}x{vs and vs['height']} (need {width}x{height})"))
    if vs:
        num, den = (vs.get("avg_frame_rate", "0/1").split("/") + ["1"])[:2]
        fps = float(num) / float(den or 1)
        checks.append(_check("frame rate", "pass" if 29 <= fps <= 31 else "warn", f"{fps:.1f} fps"))
    checks.append(_check("audio track", "pass" if au else "fail", "present" if au else "missing"))
    ratio = dur / target_duration
    checks.append(_check("duration", "fail" if dur < 5 else ("pass" if 0.6 <= ratio <= 1.5 else "warn"),
                         f"{dur:.1f}s vs {target_duration}s target"))
    checks.append(_check("file size", "pass" if size_mb <= 100 else "warn", f"{size_mb:.1f} MB"))
    stats = {}
    if au:
        stats = analyse_media(path)
        m, p = stats["mean_volume"], stats["max_volume"]
        checks.append(_check("loudness", "pass" if m > -30 else ("warn" if m > -42 else "fail"),
                             f"mean {m:.1f} dB, peak {p:.1f} dB"))
        checks.append(_check("clipping", "pass" if p < -0.1 else "warn", f"peak {p:.1f} dB"))
        frac = stats["black_seconds"] / dur
        checks.append(_check("black frames", "pass" if frac < 0.1 else ("warn" if frac < 0.3 else "fail"),
                             f"{stats['black_seconds']:.1f}s black"))
    n = len(visuals) or 1
    text_share = sum(1 for v in visuals if v["type"] == "text") / n
    checks.append(_check("stock visuals", "pass" if text_share <= 0.5 else "warn",
                         f"{sum(1 for v in visuals if v['type']=='video')} video, "
                         f"{sum(1 for v in visuals if v['type']=='image')} image, "
                         f"{sum(1 for v in visuals if v['type']=='text')} typography scenes"))
    checks.append(_check("captions", "pass" if caption_events else "fail", f"{caption_events} caption events (timing estimated)"))
    if claims_to_verify:
        checks.append(_check("fact-check", "warn", f"{len(claims_to_verify)} claim(s) need human verification before posting"))
    worst = max((c["status"] for c in checks), key=ORDER.get)
    return {"status": worst, "checks": checks, "stats": stats, "duration": round(dur, 2)}
