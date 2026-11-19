import tempfile
import unittest
from pathlib import Path

from src.autoreel.config import Settings
from src.autoreel import editor, qa
from src.autoreel.captions import build_ass, chunk_words, srt_time, ass_time, esc, _animated_caption
from src.autoreel.music import synth_music, choose_music
from src.autoreel.util import media_duration, probe
from tests.helpers import make_clip, make_image, make_voice


class CaptionTests(unittest.TestCase):
    def test_chunks_and_times(self):
        ch = chunk_words("The moon pulls on the ocean, and the water rises twice a day.")
        self.assertTrue(all(len(c.split()) <= 6 for c in ch))
        self.assertEqual(" ".join(ch), "The moon pulls on the ocean, and the water rises twice a day.")
        self.assertEqual(ass_time(3661.256), "1:01:01.26")
        self.assertEqual(srt_time(61.5), "00:01:01,500")

    def test_escape_blocks_ass_override_injection(self):
        self.assertNotIn("{", esc("hi {\\an8\\fs200} there"))

    def test_build_ass_has_kicker_and_disclaimer(self):
        scenes = [{"start": 0, "dur": 5, "audio_start": 0.3, "audio_dur": 3, "narration": "Hello there friend",
                   "text_scene": False, "kicker": "big idea"}]
        ass, srt, n = build_ass(1080, 1920, scenes, 5, "Fictional demonstration advertisement")
        self.assertIn("BIG IDEA", ass); self.assertIn("Fictional demonstration", ass)
        self.assertEqual(n, 1); self.assertIn("Hello there friend", srt)
        self.assertIn(r"\fad(110,100)", ass)
        self.assertIn(r"\c&H0000D7FF&", ass)

    def test_caption_animation_is_ass_escaped(self):
        animated = _animated_caption("Clean edits feel intentional")
        self.assertTrue(animated.startswith(r"{\fad(110,100)"))
        self.assertIn("Clean", animated)
        self.assertIn(r"\fscx92", animated)


class MusicTests(unittest.TestCase):
    def test_synth_all_moods(self):
        with tempfile.TemporaryDirectory() as d:
            for mood in ("calm", "uplifting", "cinematic", "playful", "tense"):
                p = synth_music(Path(d) / f"{mood}.wav", 6, mood)
                self.assertAlmostEqual(media_duration(p), 6, delta=0.1)

    def test_user_music_flagged_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d) / "m"; lib.mkdir(); (lib / "calm-theme.mp3").write_bytes(b"x")
            s = Settings(music_dir=lib)
            path, info = choose_music(s, "calm", 10, d)
            self.assertEqual(info["source"], "user-supplied"); self.assertIn("UNVERIFIED", info["rights"])
            s2 = Settings(music_dir=Path(d) / "none")
            _, info2 = choose_music(s2, "calm", 4, d)
            self.assertEqual(info2["source"], "synthesised")


class EditorEndToEnd(unittest.TestCase):
    def test_editor_selects_style_matched_transition_sequence(self):
        self.assertEqual(editor.transition_for("cinematic_story", 1), "fade")
        self.assertEqual(editor.transition_for("cinematic_story", 2), "dissolve")
        self.assertEqual(editor.transition_for("anime_story", 1), "pixelize")
        self.assertEqual(editor.transition_for("unknown", 1), "fade")

    def test_full_assembly_and_qa(self):
        s = Settings()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            clip, img = make_clip(d / "clip.mp4", 3), make_image(d / "img.jpg")
            visuals = [{"type": "video", "path": clip, "color": "0x14213d", "style": "cinematic_story"},
                       {"type": "image", "path": img, "color": "0x14213d", "style": "cinematic_story"},
                       {"type": "text", "path": None, "color": "0x1b2a41", "style": "cinematic_story"}]
            narr_secs = [3.0, 2.5, 2.0]
            narr = [make_voice(d / f"n{i}.wav", t) for i, t in enumerate(narr_secs)]
            durs = [editor.scene_duration(t, s.transition_seconds) for t in narr_secs]
            files = [editor.render_scene(v, du, d / f"s{i}.mp4", s) for i, (v, du) in enumerate(zip(visuals, durs))]
            for f, du in zip(files, durs):
                self.assertAlmostEqual(media_duration(f), du, delta=0.15)
            music = synth_music(d / "m.wav", sum(durs), "calm")
            info = [{"narration": "The moon pulls on the ocean every day", "audio_dur": narr_secs[0], "text_scene": False, "kicker": "Tides"},
                    {"narration": "Water rises and falls twice daily", "audio_dur": narr_secs[1], "text_scene": False},
                    {"narration": "Simple physics, endless motion", "audio_dur": narr_secs[2], "text_scene": True}]
            out = d / "final.mp4"
            res = editor.assemble(files, narr, durs, info, music, d, out, s, "Fictional demonstration advertisement",
                                  style="cinematic_story")
            expected = sum(durs) - 2 * s.transition_seconds
            self.assertAlmostEqual(media_duration(out), expected, delta=0.2)
            self.assertEqual(res["transitions"], ["fade", "dissolve"])
            streams = {x["codec_type"]: x for x in probe(out)["streams"]}
            self.assertEqual((streams["video"]["width"], streams["video"]["height"]), (1080, 1920))
            self.assertEqual(streams["video"]["codec_name"], "h264")
            self.assertIn("audio", streams)
            thumb = editor.make_thumbnail(files[0], "How tides work", d, d / "thumb.jpg", s)
            self.assertGreater(Path(thumb).stat().st_size, 5000)
            tinfo = probe(thumb)["streams"][0]
            self.assertEqual((tinfo["width"], tinfo["height"]), (1080, 1920))
            report = qa.run_qa(out, target_duration=int(round(expected)), visuals=visuals,
                               caption_events=res["caption_events"], claims_to_verify=["x"])
            names = {c["name"]: c for c in report["checks"]}
            self.assertEqual(names["resolution"]["status"], "pass")
            self.assertEqual(names["audio track"]["status"], "pass")
            self.assertEqual(names["fact-check"]["status"], "warn")
            self.assertIn(report["status"], ("pass", "warn"))

    def test_qa_fails_on_wrong_size_and_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(qa.run_qa(Path(d) / "no.mp4", target_duration=10, visuals=[], caption_events=0,
                                       claims_to_verify=[])["status"], "fail")
            bad = make_clip(Path(d) / "bad.mp4", 6)    # 1280x720, no audio
            rep = qa.run_qa(bad, target_duration=6, visuals=[{"type": "video"}], caption_events=3, claims_to_verify=[])
            self.assertEqual(rep["status"], "fail")
            self.assertEqual({c["name"]: c["status"] for c in rep["checks"]}["audio track"], "fail")


if __name__ == "__main__":
    unittest.main()
