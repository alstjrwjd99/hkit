"""Run from the kit with python3 -m unittest discover -s tests (Bash on PATH)."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


KIT = Path(__file__).resolve().parents[1]


class KitTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.task = Path(scratch.name) / "task workspace"
        self.task.mkdir()

    def install(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash, "Bash must be on PATH")
        subprocess.run(
            [bash, "install.sh", self.task.as_posix()],
            cwd=KIT, check=True, capture_output=True, timeout=30,
        )

    def snapshot(self):
        return {p.relative_to(self.task): p.read_bytes()
                for p in self.task.rglob("*") if p.is_file()}

    def test_install_and_repeat(self):
        self.install()
        installed = self.snapshot()
        for src in (KIT / "templates").rglob("*.md"):
            self.assertEqual(installed[src.relative_to(KIT / "templates")], src.read_bytes())
        for folder in [".agents/skills", ".codex/agents"]:
            for src in (KIT / folder).rglob("*"):
                if src.is_file():
                    self.assertEqual(installed[src.relative_to(KIT)], src.read_bytes())
        self.install()
        self.assertEqual(self.snapshot(), installed)

    def test_keep_existing_project(self):
        for name in ["AGENTS.md", "docs/prd.md", ".codex/agents/backend.toml",
                     ".agents/skills/eda/SKILL.md"]:
            file = self.task / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("existing project content", encoding="utf-8")
        existing = self.snapshot()
        self.install()
        installed = self.snapshot()
        for path, content in existing.items():
            self.assertEqual(installed[path], content)
        self.assertEqual(installed[Path("HYNIX_KIT_GUIDE.md")], (KIT / "AGENTS.md").read_bytes())
        self.assertFalse((self.task / ".agents/skills/eda/scripts").exists())
        self.assertTrue((self.task / ".codex/agents/frontend.toml").is_file())

    def test_profile_mixed_records(self):
        self.install()
        source = self.task / "input.csv"
        source.write_text('id,value\n"bus,1",10\n"bus,1",10\n2, \nwrong\n', encoding="utf-8-sig")
        script = self.task / ".agents/skills/eda/scripts/profile_csv.py"
        run = subprocess.run([sys.executable, script, source], check=True, capture_output=True)
        report = json.loads(run.stdout)
        expected = {
            "records": 4, "valid_width": 3, "wrong_width": 1,
            "duplicate_rows_after_first": 1, "missing_in_valid_rows": {"id": 0, "value": 1},
        }
        self.assertEqual({name: report[name] for name in expected}, expected)
        self.assertEqual(report["columns"]["value"]["missing_rate"], 1 / 3)
