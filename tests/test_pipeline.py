import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.autoreel import cli, publishing, store
from src.autoreel.config import Settings
from src.autoreel.pipeline import generate_project
from src.autoreel.util import PipelineError, probe
from src.media import MediaManager
from tests.helpers import FakeStock, ToneTTS, make_clip, make_image
from tests.test_llm_script_research import good_script

NOW = dt.datetime(2026, 11, 16, 10, 30, 0, tzinfo=dt.timezone.utc)


class FakeGemini:
    def __init__(self, script):
        self.script = script

    def generate_json(self, prompt, **kw):
        return self.script


def settings(tmp):
    s = Settings(output_root=Path(tmp) / "out", data_dir=Path(tmp) / "data", cache_dir=Path(tmp) / "cache",
                 music_dir=Path(tmp) / "nomusic")
    s.secrets = ["SECRET-VALUE-123"]
    return s


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.clip, self.img = make_clip(self.d / "c.mp4", 4), make_image(self.d / "i.jpg")

    def test_success_end_to_end(self):
        script = good_script(15)
        script["scenes"][2]["search_query"] = "image tree"       # -> still image
        script["scenes"][2]["fallback_query"] = "image tree"
        stock = FakeStock(self.clip, self.img, video_scenes=1)    # scene1 video, scene2 -> typography
        s = settings(self.d)
        p = generate_project(s, "How tides work", 15, "educational", gemini=FakeGemini(script),
                             media=MediaManager([stock]), tts=ToneTTS(), now=NOW, repo="me/repo")
        self.assertIn(p["status"], ("needs_review",))
        out = s.output_root / p["id"]
        for name in ("final.mp4", "thumbnail.jpg", "captions.srt", "script.json", "project.json"):
            self.assertTrue((out / name).exists(), name)
        self.assertFalse((out / "work").exists())                 # intermediates cleaned up
        v = [x for x in probe(out / "final.mp4")["streams"] if x["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertEqual([x["type"] for x in p["scene_visuals"]], ["video", "text", "image"])
        self.assertEqual(p["assets"]["video_url"], f"https://github.com/me/repo/releases/download/project-{p['id']}/final.mp4")
        self.assertIn("FakeStock", p["credits"]); self.assertIn("Stock footage/images: FakeStock", p["publish"]["caption"])
        self.assertEqual(p["music"]["source"], "synthesised")
        self.assertEqual([e["stage"] for e in p["log"]][:3], ["script", "narration", "visuals"])
        self.assertTrue(all(e["ok"] for e in p["log"]))
        self.assertNotEqual(p["qa"]["status"], "fail")
        idx = store.load_index(s.data_dir)
        self.assertEqual(idx["projects"][0]["id"], p["id"])
        self.assertEqual(store.get_project(s.data_dir, p["id"])["status"], "needs_review")
        # the committed record must not contain local filesystem paths
        self.assertNotIn(str(self.d), json.dumps(store.get_project(s.data_dir, p["id"])))

    def test_no_media_provider_uses_typography(self):
        s = settings(self.d)
        p = generate_project(s, "Quiet mornings", 15, "typography_quote", gemini=FakeGemini(good_script(15)),
                             media=None, tts=ToneTTS(), now=NOW)
        self.assertTrue(all(v["type"] == "text" for v in p["scene_visuals"]))
        self.assertTrue(any("typography" in e["message"] for e in p["log"]))

    def test_failure_is_recorded_and_reraised(self):
        class BadTTS(ToneTTS):
            def synthesize(self, text, out):
                raise PipelineError("engine exploded SECRET-VALUE-123")
        s = settings(self.d)
        with self.assertRaises(PipelineError):
            generate_project(s, "How tides work", 15, "educational", gemini=FakeGemini(good_script(15)),
                             media=None, tts=BadTTS(), now=NOW)
        rows = store.load_index(s.data_dir)["projects"]
        self.assertEqual(rows[0]["status"], "failed")
        rec = store.get_project(s.data_dir, rows[0]["id"])
        self.assertIn("engine exploded", rec["error"]); self.assertNotIn("SECRET-VALUE-123", json.dumps(rec))
        self.assertFalse(rec["log"][-1]["ok"])

    def test_invalid_input_rejected_before_any_work(self):
        s = settings(self.d)
        with self.assertRaises(PipelineError):
            generate_project(s, "x", 15, "educational", gemini=None, media=None, tts=None, now=NOW)
        self.assertFalse(s.output_root.exists())


class StoreAndPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def proj(self, pid="20261116-103000-demo", status="needs_review", qa="pass"):
        p = {"id": pid, "created_at": "2026-11-16T10:30:00Z", "status": status, "topic": "demo", "title": "Demo",
             "qa": {"status": qa}, "approval": {"decision": None}}
        store.save_project(self.d, p); return p

    def test_approve_reject_flow_and_history(self):
        self.proj()
        self.assertEqual(store.set_status(self.d, "20261116-103000-demo", "approve", "looks good")["status"], "approved")
        self.assertEqual(store.load_index(self.d)["projects"][0]["status"], "approved")
        self.assertEqual(store.set_status(self.d, "20261116-103000-demo", "reject")["status"], "rejected")

    def test_cannot_approve_failed_or_qa_failed(self):
        self.proj("20261116-103001-bad", status="failed")
        self.proj("20261116-103002-qa", qa="fail")
        for pid in ("20261116-103001-bad", "20261116-103002-qa"):
            with self.assertRaises(PipelineError):
                store.set_status(self.d, pid, "approve")

    def test_id_validation_blocks_path_traversal(self):
        for bad in ("../../etc/passwd", "x", "20261116-103000-Demo", "20261116-103000-a/b", ""):
            with self.assertRaises(PipelineError):
                store.get_project(self.d, bad)

    def test_index_sorted_newest_first(self):
        self.proj("20261116-103000-a"); p = self.proj("20261117-090000-b"); p["created_at"] = "2026-11-17T09:00:00Z"
        store.save_project(self.d, p)
        self.assertEqual([r["id"] for r in store.load_index(self.d)["projects"]],
                         ["20261117-090000-b", "20261116-103000-a"])

    def test_publish_guard(self):
        p = self.proj()
        with self.assertRaises(publishing.NotApproved):
            publishing.InstagramPublisher().publish(p)
        approved = store.set_status(self.d, p["id"], "approve")
        with self.assertRaises(NotImplementedError):            # approved, but publishing is not built
            publishing.InstagramPublisher().publish(approved)
        self.assertIn("checklist", publishing.instagram_package(approved))

    def test_cli_set_status(self):
        self.proj()
        with mock.patch.dict(os.environ, {"AUTOREEL_DATA": str(self.d)}):
            self.assertEqual(cli.main(["set-status", "--id", "20261116-103000-demo", "--decision", "approve"]), 0)
            self.assertEqual(cli.main(["set-status", "--id", "nope", "--decision", "approve"]), 1)
        self.assertEqual(store.get_project(self.d, "20261116-103000-demo")["status"], "approved")


if __name__ == "__main__":
    unittest.main()
