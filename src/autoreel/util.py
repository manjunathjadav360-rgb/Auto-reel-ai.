from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path


class PipelineError(Exception):
    """A stage failed in a way the user should see (message is safe to display)."""


class RedactFilter(logging.Filter):
    """Removes secret values from every log line."""

    def __init__(self, secrets):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record):
        msg = record.getMessage()
        for s in self.secrets:
            msg = msg.replace(s, "***")
        record.msg, record.args = msg, ()
        return True


def setup_logging(secrets=(), level=logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter(secrets))
    root.addHandler(handler)


def redact(text: str, secrets) -> str:
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "***")
    return text


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].strip("-")) or "video"


def run(cmd: list, *, timeout: int = 900, input_text: str = None, cwd=None) -> subprocess.CompletedProcess:
    """Run a command without a shell. Raises PipelineError with the stderr tail."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              input=input_text, cwd=cwd)
    except FileNotFoundError:
        raise PipelineError(f"Required program not found: {cmd[0]}") from None
    except subprocess.TimeoutExpired:
        raise PipelineError(f"{cmd[0]} timed out after {timeout}s") from None
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise PipelineError(f"{cmd[0]} failed: " + " | ".join(tail))
    return proc


def probe(path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
               "-show_streams", str(path)]).stdout
    return json.loads(out)


def media_duration(path) -> float:
    return float(probe(path)["format"]["duration"])


def write_json(path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
