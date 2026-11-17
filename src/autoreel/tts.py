"""Text-to-speech engines. Piper (neural, offline) preferred; eSpeak NG fallback."""
from __future__ import annotations

import importlib.util
import logging
import re
import shutil
import sys
from pathlib import Path

from .util import PipelineError, run

log = logging.getLogger("autoreel.tts")


def clean_text(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]", "", text)     # emoji
    text = text.replace("&", " and ").replace("\u2014", ", ").replace("\u2013", ", ")
    return re.sub(r"\s+", " ", text).strip()


class PiperEngine:
    name = "piper"

    def __init__(self, voice: str, voices_dir):
        self.voice = voice
        self.voices_dir = Path(voices_dir)
        self.model = self.voices_dir / f"{voice}.onnx"
        self.license_note = (f"Piper voice '{voice}'. Voice-model licences differ: read the MODEL_CARD "
                             "for this voice in huggingface.co/rhasspy/piper-voices before commercial use "
                             "(not verified by this project).")

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("piper") is not None

    def ensure_voice(self):
        if self.model.exists() and Path(str(self.model) + ".json").exists():
            return
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        log.info("Downloading Piper voice %s", self.voice)
        run([sys.executable, "-m", "piper.download_voices", self.voice],
            cwd=self.voices_dir, timeout=600)
        if not self.model.exists():
            raise PipelineError(f"Piper voice {self.voice} was not downloaded")

    def synthesize(self, text: str, out_wav) -> None:
        self.ensure_voice()
        run([sys.executable, "-m", "piper", "-m", str(self.model), "-f", str(out_wav)],
            input_text=text, timeout=300)


class EspeakEngine:
    name = "espeak"
    voice = "en-us"
    license_note = ("eSpeak NG synthetic voice (robotic). The software is GPL; generated audio is "
                    "generally not encumbered, but this is not legal advice.")

    @staticmethod
    def installed() -> bool:
        return shutil.which("espeak-ng") is not None

    def synthesize(self, text: str, out_wav) -> None:
        run(["espeak-ng", "-v", "en-us", "-s", "150", "-p", "42", "-w", str(out_wav), "--stdin"],
            input_text=text, timeout=120)


def pick_engine(settings):
    want = settings.tts_engine
    if want in ("auto", "piper") and PiperEngine.installed():
        return PiperEngine(settings.piper_voice, settings.voices_dir)
    if want in ("auto", "espeak") and EspeakEngine.installed():
        if want == "auto":
            log.warning("Piper not installed; using eSpeak NG (lower quality).")
        return EspeakEngine()
    raise PipelineError(
        "No text-to-speech engine available. Install Piper (pip install piper-tts) "
        "or eSpeak NG (apt install espeak-ng).")
