"""Caption chunking and ASS/SRT generation with subtle kinetic reveals."""
from __future__ import annotations

import re

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,68,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,90,90,470,1
Style: Card,DejaVu Sans,86,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,5,110,110,0,1
Style: Kicker,DejaVu Sans,50,&H0000D7FF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,8,90,90,230,1
Style: Disc,DejaVu Sans,32,&H00E0E0E0,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,8,60,60,70,1
Style: Title,DejaVu Sans,96,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,8,4,5,100,100,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def esc(text: str) -> str:
    text = text.replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"\s*\n\s*", r"\\N", text.strip())


def chunk_words(text: str, max_words: int = 5, max_chars: int = 32) -> list:
    words, chunks, cur = text.split(), [], []
    for w in words:
        cur.append(w)
        line = " ".join(cur)
        ends = w[-1] in ".!?,;:"
        if len(cur) >= max_words or len(line) >= max_chars or (ends and len(cur) >= 2):
            chunks.append(line)
            cur = []
    if cur:
        if chunks and len(cur) == 1:
            chunks[-1] += " " + cur[0]
        else:
            chunks.append(" ".join(cur))
    return chunks


def scene_events(narration: str, audio_start: float, audio_dur: float) -> list:
    """[(start, end, text)] spread over the narration clip."""
    chunks = chunk_words(narration)
    total = sum(len(c) for c in chunks) or 1
    events, t = [], audio_start
    for c in chunks:
        d = max(0.5, audio_dur * len(c) / total)
        events.append((t, min(t + d, audio_start + audio_dur + 0.15), c))
        t += d
    return events


def _animated_caption(text: str) -> str:
    """Scale/fade a caption in and accent its opening word."""
    words = text.split()
    if not words:
        return ""
    animated = r"{\fad(110,100)\fscx92\fscy92\t(0,150,\fscx100\fscy100)}"
    accent = r"{\c&H0000D7FF&}" + esc(words[0]) + r"{\c&H00FFFFFF&}"
    rest = " ".join(esc(word) for word in words[1:])
    return animated + accent + ((" " + rest) if rest else "")


def build_ass(width: int, height: int, scenes: list, total: float, disclaimer: str = "") -> tuple:
    """scenes: [{start, audio_start, audio_dur, narration, text_scene, kicker}] on the GLOBAL timeline."""
    lines, srt, n = [HEADER.format(w=width, h=height)], [], 0
    for sc in scenes:
        style = "Card" if sc.get("text_scene") else "Cap"
        for (a, b, text) in scene_events(sc["narration"], sc["audio_start"], sc["audio_dur"]):
            n += 1
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{_animated_caption(text)}")
            srt.append(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n")
        if sc.get("kicker"):
            kicker = r"{\fad(240,190)\fscx88\fscy88\t(0,180,\fscx100\fscy100)}"
            lines.append(f"Dialogue: 1,{ass_time(sc['start'] + 0.2)},{ass_time(sc['start'] + min(3.0, sc['dur'] - 0.2))},"
                         f"Kicker,,0,0,0,,{kicker}{esc(sc['kicker'].upper())}")
    if disclaimer:
        lines.append(f"Dialogue: 2,{ass_time(0)},{ass_time(total)},Disc,,0,0,0,,{esc(disclaimer)}")
    return "\n".join(lines) + "\n", "\n".join(srt), n


def title_ass(width: int, height: int, title: str) -> str:
    words = title.split()
    mid = (len(words) + 1) // 2
    wrapped = " ".join(words) if len(title) <= 22 else " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
    return HEADER.format(w=width, h=height) + \
        f"Dialogue: 0,{ass_time(0)},{ass_time(5)},Title,,0,0,0,,{esc(wrapped.upper())}\n"
