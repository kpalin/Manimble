import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "apps" / "linux"))
from manimble import latex_packages
from manimble_gtk.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.project = self.root / "project"
        self.deck = self.project / "deck"
        self.deck.mkdir(parents=True)
        (self.deck / "slides.py").write_text("class Welcome: pass\n", encoding="utf-8")
        (self.deck / "order.txt").write_text("Welcome\n", encoding="utf-8")
        (self.project / "assets").mkdir()

    def make_workspace(self):
        workspace = Workspace(self.deck)
        self.addCleanup(workspace.discard)
        return workspace

    def test_save_copies_deck_edits_but_not_generated_output(self):
        workspace = self.make_workspace()
        (workspace.work / "slides.py").write_text("class Welcome: ...\n", encoding="utf-8")
        (workspace.work / "new.py").write_text("value = 1\n", encoding="utf-8")
        (workspace.work / "slides").mkdir()
        (workspace.work / "slides" / "render.json").write_text("generated", encoding="utf-8")

        changed = workspace.save()

        self.assertIn(Path("slides.py"), changed)
        self.assertIn(Path("new.py"), changed)
        self.assertEqual((self.deck / "slides.py").read_text(encoding="utf-8"), "class Welcome: ...\n")
        self.assertTrue((self.deck / "new.py").is_file())
        self.assertFalse((self.deck / "slides" / "render.json").exists())
        self.assertEqual(workspace.changed_files, [])

    def test_save_refuses_to_overwrite_a_concurrent_original_edit(self):
        workspace = self.make_workspace()
        (workspace.work / "slides.py").write_text("class Welcome: ...\n", encoding="utf-8")
        (self.deck / "slides.py").write_text("class Welcome: changed elsewhere\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "changed outside Manimble"):
            workspace.save()

        self.assertEqual((self.deck / "slides.py").read_text(encoding="utf-8"), "class Welcome: changed elsewhere\n")

    def test_relative_project_assets_remain_available_in_the_working_copy(self):
        workspace = self.make_workspace()

        self.assertTrue((workspace.project_root / "assets").is_symlink())
        self.assertTrue((workspace.project_root / "assets").resolve().is_dir())

    def test_linux_does_not_attempt_macos_tex_privilege_escalation(self):
        tools = {"tlmgr": "/usr/bin/tlmgr", "kpsewhich": "/usr/bin/kpsewhich"}
        with (
            patch.object(latex_packages.sys, "platform", "linux"),
            patch.object(latex_packages, "find_tool", side_effect=tools.get),
            patch.object(latex_packages, "package_of", return_value="test-package"),
            patch.object(latex_packages.subprocess, "run", return_value=SimpleNamespace(
                stdout="/usr/local/texlive/2025", returncode=0, stderr=""
            )) as run,
            patch.object(latex_packages.os, "access", return_value=False),
        ):
            result = latex_packages.install(["missing.sty"])

        self.assertFalse(result["ok"])
        self.assertIn("TeX Live package tree is not writable", result["error"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/kpsewhich")


if __name__ == "__main__":
    unittest.main()
