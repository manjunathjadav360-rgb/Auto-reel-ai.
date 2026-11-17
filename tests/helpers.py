from pathlib import Path
"""Test doubles that create REAL media files with FFmpeg (no network needed)."""
import subprocess
from pathlib import Path


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def make_clip(path, seconds=4, w=1280, h=720):
    ff("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=25:duration={seconds}",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return str(path)


def make_image(path, w=720, h=1280):
    ff("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}", "-frames:v", "1", str(path))
    return str(path)


def make_voice(path, seconds):
    """Stand-in 'narration': speech-band tone with a syllable-like pulse."""
    ff("-f", "lavfi", "-i", f"sine=frequency=180:duration={seconds}:sample_rate=22050",
       "-af", "tremolo=f=4:d=0.8,volume=0.8", "-ac", "1", str(path))
    return str(path)


class ToneTTS:
    """TEST DOUBLE ONLY: duration proportional to word count. Never used in production."""
    name, voice, license_note = "test-tone", "none", "test double"

    def synthesize(self, text, out_wav):
        make_voice(out_wav, max(1.5, 0.4 * len(text.split())))


import shutil
from src.media import MediaAsset, MediaManager
from src.media.base import MediaProvider


class FakeStock(MediaProvider):
    """Serves local files as if they were stock media (no network)."""
    name, display_name, home_url = "fakestock", "FakeStock", "https://example.test"
    license_name, license_url = "Test License", "https://example.test/license"

    def __init__(self, clip, image, video_scenes=2):
        self.clip, self.image, self.video_budget = clip, image, video_scenes
        self.queries = []

    @classmethod
    def from_env(cls, env, cache_dir):
        raise NotImplementedError

    def _asset(self, kind, i, path, w, h):
        return MediaAsset(provider=self.name, source_name=self.display_name, source_url=self.home_url,
                          license_name=self.license_name, license_url=self.license_url,
                          asset_id=f"{kind}{i}", kind=kind, page_url=f"https://example.test/{kind}/{i}",
                          download_url=path, width=w, height=h, creator="Tester", duration=4.0)

    def search_videos(self, query, **o):
        self.queries.append(("video", query))
        if self.video_budget <= 0:
            return []
        self.video_budget -= 1
        n = len(self.queries)
        return [self._asset("video", n, self.clip, 1280, 720)]

    def search_images(self, query, **o):
        self.queries.append(("image", query))
        if "image" in query:                       # only queries containing 'image' get a still
            return [self._asset("image", len(self.queries), self.image, 720, 1280)]
        return []

    def download(self, asset, dest_dir):
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(dest_dir) / f"{asset.asset_id}{Path(asset.download_url).suffix}"
        shutil.copy(asset.download_url, dest)
        asset.local_path = str(dest)
        return asset
