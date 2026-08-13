import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LINTER_SCRIPT = REPO_ROOT / "tools" / "lint_skills.py"


def run_linter(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "lint_skills.py")],
        capture_output=True,
        text=True,
    )


class LinterRepoFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        tools = self.root / "tools"
        tools.mkdir()
        shutil.copy(LINTER_SCRIPT, tools / "lint_skills.py")
        # The Python-test CI job does not install PyYAML; the separate lint job
        # does. These config-focused tests only need a valid frontmatter map.
        (tools / "yaml.py").write_text(
            "class YAMLError(Exception):\n"
            "    pass\n\n"
            "def safe_load(_text):\n"
            "    return {'name': 'example', 'description': 'Example skill'}\n",
            encoding="utf-8",
        )

        command = self.root / ".grok" / "commands" / "setup.md"
        command.parent.mkdir(parents=True)
        command.write_text("# /setup - Test setup command\n", encoding="utf-8")

        skill = self.root / ".grok" / "skills" / "example" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: example\ndescription: Example skill\n---\n",
            encoding="utf-8",
        )

        self.config = self.root / ".grok" / "config.toml"
        self.write_config('["permission"]\nallow = []\n')

    def write_config(self, text: str) -> None:
        # Accept either full TOML or just the body; always write valid TOML.
        if text.strip().startswith("["):
            self.config.write_text(text, encoding="utf-8")
        else:
            self.config.write_text(text, encoding="utf-8")


class ConfigShapeTests(LinterRepoFixture):
    def test_valid_config_pass(self):
        self.write_config(
            '[permission]\nallow = ["Bash(bun run *)"]\n'
        )
        result = run_linter(self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("lint_skills: OK", result.stdout)

    def test_invalid_toml_fails_cleanly(self):
        self.config.write_text("[[[not toml", encoding="utf-8")

        result = run_linter(self.root)

        self.assertEqual(result.returncode, 1)
        self.assertIn(".grok/config.toml", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_table_permission_fails_cleanly(self):
        self.write_config('permission = "nope"\n')

        result = run_linter(self.root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("permission", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_list_allow_fails_cleanly(self):
        self.write_config('[permission]\nallow = "Bash(*)"\n')

        result = run_linter(self.root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("permission.allow", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
