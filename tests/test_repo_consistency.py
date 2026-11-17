import re
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

from src.autoreel import cli
from src.autoreel.config import STYLES

ROOT = Path(__file__).resolve().parent.parent


class ConsistencyTests(unittest.TestCase):
    def test_styles_match_dashboard_and_workflow(self):
        lib = (ROOT / "docs/lib.js").read_text()
        wf = yaml.safe_load((ROOT / ".github/workflows/studio.yml").read_text())
        opts = wf[True]["workflow_dispatch"]["inputs"]["style"]["options"]
        self.assertEqual(set(opts), set(STYLES))
        for key in STYLES:
            self.assertRegex(lib, rf"\b{key}:")
        self.assertEqual(set(re.findall(r"^\s{4}(\w+): \"", lib, re.M)) & set(STYLES), set(STYLES))

    def test_workflow_never_inlines_user_input_into_shell(self):
        text = (ROOT / ".github/workflows/studio.yml").read_text()
        for line in text.splitlines():
            if line.strip().startswith(("run:", "python -m", "gh release", "git ")):
                self.assertNotIn("${{ inputs", line)
                self.assertNotIn("${{ github.event.inputs", line)

    def test_no_secret_like_strings_committed(self):
        pattern = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|ghp_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{40,}")
        for p in ROOT.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".js", ".yml", ".md", ".html", ".json", ".example"} \
                    and ".git/" not in str(p):
                self.assertIsNone(pattern.search(p.read_text(errors="ignore")), str(p))

    def test_dashboard_logic_tests_in_node(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        r = subprocess.run(["node", "--test", str(ROOT / "docs/test_lib.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-800:])

    def test_doctor_runs_and_never_prints_keys(self):
        import io, os
        from contextlib import redirect_stdout
        from unittest import mock
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "AIza-DO-NOT-PRINT-ME", "PIXABAY_API_KEY": "PIX-DO-NOT-PRINT"}), \
                redirect_stdout(buf):
            cli.cmd_doctor(cli.Settings.from_env(), None)
        out = buf.getvalue()
        self.assertIn("ffmpeg", out); self.assertNotIn("DO-NOT-PRINT", out)


if __name__ == "__main__":
    unittest.main()
