import json
import tempfile
import unittest
from pathlib import Path

from src.media import (MediaAuthError, MediaConfigError, MediaDownloadError,
                       MediaProviderError, MediaRateLimitError, credits_short,
                       credits_text, build_manager_from_env, MediaManager)
from src.media.base import MediaProvider
from src.media.cache import JsonCache
from src.media.pixabay import (HttpResponse, PixabayProvider, RateLimiter,
                               pick_rendition)

KEY = "SECRET-KEY-123"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 100
JPG = b"\xff\xd8\xff\xe0" + b"0" * 100


def ok(payload, headers=None):
    return HttpResponse(200, headers or {}, json.dumps(payload).encode(), "u")


def rend(w, h, size, name="x"):
    return {"url": f"https://cdn.pixabay.com/video/{name}.mp4", "width": w,
            "height": h, "size": size, "thumbnail": "https://cdn.pixabay.com/t.jpg"}


def video_hit(vid, vertical=False, duration=10):
    if vertical:
        vids = {"large": rend(2160, 3840, 60_000_000, "l"), "medium": rend(1080, 1920, 9_000_000, "m"),
                "small": rend(720, 1280, 4_000_000, "s"), "tiny": rend(540, 960, 2_000_000, "t")}
    else:
        vids = {"large": rend(3840, 2160, 40_000_000, "l"), "medium": rend(1920, 1080, 9_000_000, "m"),
                "small": rend(1280, 720, 4_000_000, "s"), "tiny": rend(960, 540, 2_000_000, "t")}
    return {"id": vid, "pageURL": f"https://pixabay.com/videos/id-{vid}/", "tags": "a, b",
            "duration": duration, "videos": vids, "user": "Maker", "user_id": 7}


class FakeTransport:
    def __init__(self, responses):
        self.responses, self.urls = list(responses), []

    def fetch(self, url, max_bytes=0):
        self.urls.append(url)
        return self.responses.pop(0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sleeps = []

    def make(self, responses, **kw):
        self.t = FakeTransport(responses)
        return PixabayProvider(KEY, self.tmp.name, transport=self.t,
                               sleep=self.sleeps.append, **kw)


class SearchTests(Base):
    def test_video_vertical_first_and_flags(self):
        p = self.make([ok({"hits": [video_hit(1), video_hit(2, vertical=True)]})])
        r = p.search_videos("sea")
        self.assertEqual([a.asset_id for a in r], ["2", "1"])
        self.assertTrue(r[0].is_vertical and not r[0].needs_crop_for_9x16)
        self.assertTrue(r[1].needs_crop_for_9x16)
        self.assertEqual(r[0].meta["rendition"], "medium")      # 1080x1920, no upscale
        self.assertEqual(r[1].meta["rendition"], "large")       # 4K landscape crop is sharp
        self.assertEqual(r[0].creator_url, "https://pixabay.com/users/Maker-7/")

    def test_video_vertical_only_and_duration(self):
        p = self.make([ok({"hits": [video_hit(1), video_hit(2, True, 3), video_hit(3, True, 12)]})])
        r = p.search_videos("sea", orientation="vertical", min_duration=5)
        self.assertEqual([a.asset_id for a in r], ["3"])

    def test_image_sends_vertical_and_key_only_in_url(self):
        hit = {"id": 5, "pageURL": "https://pixabay.com/photos/x-5/", "tags": "t",
               "largeImageURL": "https://pixabay.com/get/abc_1280.jpg",
               "imageWidth": 4000, "imageHeight": 6000, "user": "U", "user_id": 1}
        p = self.make([ok({"hits": [hit] * 3})])
        r = p.search_images("tree")
        self.assertIn("orientation=vertical", self.t.urls[0])
        self.assertIn("key=" + KEY, self.t.urls[0])
        self.assertEqual((r[0].width, r[0].height), (853, 1280))
        self.assertNotIn(KEY, repr(p))

    def test_image_falls_back_to_any_orientation(self):
        h = lambda i: {"id": i, "pageURL": "https://pixabay.com/p/", "webformatURL":
                       "https://pixabay.com/get/a_640.jpg", "imageWidth": 640, "imageHeight": 360}
        p = self.make([ok({"hits": []}), ok({"hits": [h(1), h(2)]})])
        r = p.search_images("tree")
        self.assertEqual(len(r), 2)
        self.assertIn("orientation=all", self.t.urls[1])

    def test_validation(self):
        p = self.make([])
        with self.assertRaises(ValueError):
            p.search_videos("   ")
        with self.assertRaises(ValueError):
            p.search_videos("x", category="nope")
        with self.assertRaises(ValueError):
            p.search_videos("x", orientation="sideways")

    def test_query_truncated_to_100(self):
        p = self.make([ok({"hits": []})])
        p.search_videos("a" * 300)
        self.assertIn("q=" + "a" * 100 + "&", self.t.urls[0])
        self.assertNotIn("a" * 101, self.t.urls[0])


class CacheAndLimitTests(Base):
    def test_second_search_uses_cache_without_http(self):
        p = self.make([ok({"hits": [video_hit(1)]})])
        p.search_videos("sea"); p.search_videos("sea")
        self.assertEqual(len(self.t.urls), 1)

    def test_cache_expires_after_24h(self):
        now = [1000.0]
        c = JsonCache(self.tmp.name + "/c", ttl_seconds=86400, clock=lambda: now[0])
        c.set("k", {"a": 1})
        now[0] += 86399; self.assertEqual(c.get("k"), {"a": 1})
        now[0] += 2;     self.assertIsNone(c.get("k"))

    def test_cache_key_has_no_api_key(self):
        p = self.make([ok({"hits": []})])
        p.search_videos("sea")
        blob = "".join(f.read_text() for f in Path(self.tmp.name).rglob("*.json"))
        self.assertNotIn(KEY, blob)

    def test_429_then_success(self):
        r429 = HttpResponse(429, {"x-ratelimit-reset": "12"}, b"API rate limit exceeded", "u")
        p = self.make([r429, ok({"hits": []})])
        self.assertEqual(p.search_videos("sea"), [])
        self.assertIn(12.0, self.sleeps)

    def test_429_exhausted(self):
        r429 = HttpResponse(429, {"x-ratelimit-reset": "500"}, b"API rate limit exceeded", "u")
        p = self.make([r429, r429, r429])
        with self.assertRaises(MediaRateLimitError) as cm:
            p.search_videos("sea")
        self.assertEqual(cm.exception.retry_after, 65.0)         # capped

    def test_remaining_header_triggers_wait(self):
        p = self.make([ok({"hits": []}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9"}),
                       ok({"hits": []})])
        p.search_videos("one"); p.search_videos("two")
        self.assertTrue(any(8 <= s <= 9.01 for s in self.sleeps))

    def test_5xx_retries_then_errors(self):
        bad = HttpResponse(503, {}, b"down", "u")
        p = self.make([bad, bad, bad])
        with self.assertRaises(MediaProviderError):
            p.search_videos("sea")
        self.assertEqual(self.sleeps, [2, 4])

    def test_auth_error_and_key_redaction(self):
        p = self.make([HttpResponse(400, {}, f"[ERROR 400] Invalid key {KEY}".encode(), "u")])
        with self.assertRaises(MediaAuthError) as cm:
            p.search_videos("sea")
        self.assertNotIn(KEY, str(cm.exception))

    def test_invalid_json(self):
        p = self.make([HttpResponse(200, {}, b"<html>", "u")])
        with self.assertRaises(MediaProviderError):
            p.search_videos("sea")

    def test_sliding_window(self):
        t = [0.0]; slept = []
        def sleep(s): slept.append(s); t[0] += s
        rl = RateLimiter(max_calls=2, period=60, clock=lambda: t[0], sleep=sleep)
        rl.acquire(); rl.acquire(); rl.acquire()
        self.assertEqual(slept, [60.0])


class RenditionTests(unittest.TestCase):
    def test_pick(self):
        c = [dict(name="l", **rend(3840, 2160, 40e6)), dict(name="m", **rend(1920, 1080, 9e6))]
        self.assertEqual(pick_rendition(c)["name"], "l")
        self.assertEqual(pick_rendition(c, max_bytes=20_000_000)["name"], "m")  # least upscale
        self.assertIsNone(pick_rendition([{"url": "", "width": 1, "height": 1}]))


class DownloadTests(Base):
    def asset(self, p, kind="video", url="https://cdn.pixabay.com/video/m.mp4", id="9"):
        a = p._video_from_hit(video_hit(int(id)), (1080, 1920)) if kind == "video" else \
            p._image_from_hit({"id": int(id), "pageURL": "https://pixabay.com/p/", "largeImageURL": url,
                               "imageWidth": 1000, "imageHeight": 2000})
        a.download_url = url
        return a

    def test_download_validates_and_writes_sidecar_and_reuses(self):
        p = self.make([HttpResponse(200, {}, MP4, "https://cdn.pixabay.com/video/m.mp4")])
        a = p.download(self.asset(p), self.tmp.name + "/assets")
        self.assertTrue(Path(a.local_path).read_bytes().startswith(b"\x00\x00\x00\x18ftyp"))
        side = json.loads(Path(a.local_path).with_suffix(".json").read_text())
        self.assertIn("Not generated by AUTO REEL AI", side["credits"])
        n = len(self.t.urls)
        p.download(self.asset(p), self.tmp.name + "/assets")     # reuse, no network
        self.assertEqual(len(self.t.urls), n)
        self.assertEqual(p.downloads_used, 1)

    def test_rejects_foreign_host_wrong_type_redirect(self):
        p = self.make([HttpResponse(200, {}, b"<html>notvideo", "https://cdn.pixabay.com/x"),
                       HttpResponse(200, {}, MP4, "https://evil.example/x.mp4")])
        with self.assertRaises(MediaDownloadError):
            p.download(self.asset(p, url="http://evil.example/a.mp4"), self.tmp.name + "/a")
        with self.assertRaises(MediaDownloadError):
            p.download(self.asset(p), self.tmp.name + "/a")       # not an mp4
        with self.assertRaises(MediaDownloadError):
            p.download(self.asset(p, id="10"), self.tmp.name + "/a")  # redirect off-host

    def test_download_budget(self):
        p = self.make([HttpResponse(200, {}, MP4, "https://cdn.pixabay.com/a")] * 3, max_downloads=2)
        for i in (1, 2):
            p.download(self.asset(p, id=str(i)), self.tmp.name + "/a")
        with self.assertRaises(MediaDownloadError):
            p.download(self.asset(p, id="3"), self.tmp.name + "/a")

    def test_expired_image_url_is_refreshed(self):
        fresh = {"hits": [{"id": 4, "pageURL": "https://pixabay.com/p/",
                           "largeImageURL": "https://pixabay.com/get/new_1280.jpg",
                           "imageWidth": 1000, "imageHeight": 2000}]}
        p = self.make([HttpResponse(404, {}, b"", "u"), ok(fresh),
                       HttpResponse(200, {}, JPG, "https://pixabay.com/get/new_1280.jpg")])
        a = p.download(self.asset(p, "image", "https://pixabay.com/get/old_1280.jpg", "4"),
                       self.tmp.name + "/a")
        self.assertTrue(a.local_path.endswith(".jpg"))
        self.assertIn("id=4", self.t.urls[1])


class ManagerAndCreditTests(Base):
    def test_missing_key(self):
        with self.assertRaises(MediaConfigError):
            PixabayProvider.from_env({}, self.tmp.name)
        with self.assertRaises(MediaConfigError):
            build_manager_from_env({"MEDIA_PROVIDERS": "pixabay"}, self.tmp.name)
        with self.assertRaises(MediaConfigError):
            build_manager_from_env({"MEDIA_PROVIDERS": "nope"}, self.tmp.name)

    def test_from_env_manager(self):
        m = build_manager_from_env({"PIXABAY_API_KEY": KEY}, self.tmp.name)
        self.assertIn("Pixabay", m.source_notice())

    def test_fallback_to_second_provider_and_issue_logged(self):
        class Dead(MediaProvider):
            name = "dead"; display_name = "Dead"
            @classmethod
            def from_env(cls, env, cache_dir): return cls()
            def search_videos(self, q, **o): raise MediaRateLimitError("limit", 5)
            def search_images(self, q, **o): return []
            def download(self, a, d): return a
        good = self.make([ok({"hits": [video_hit(1)]})])
        m = MediaManager([Dead(), good])
        self.assertEqual(len(m.search_videos("sea")), 1)
        self.assertEqual(m.issues[0]["provider"], "dead")

    def test_all_providers_fail_returns_empty(self):
        p = self.make([HttpResponse(503, {}, b"x", "u")] * 3)
        m = MediaManager([p])
        self.assertEqual(m.search_videos("sea"), [])
        self.assertEqual(len(m.issues), 1)

    def test_credits(self):
        p = self.make([ok({"hits": [video_hit(1), video_hit(1)]})])
        assets = p.search_videos("sea")
        text = credits_text(assets)
        self.assertIn("Pixabay", text)
        self.assertIn("Not generated by AUTO REEL AI", text)
        self.assertEqual(text.count("pixabay.com/videos/id-1/"), 1)   # de-duplicated
        self.assertIn("creators: Maker", credits_short(assets))
        self.assertEqual(credits_text([]), "")


if __name__ == "__main__":
    unittest.main()
