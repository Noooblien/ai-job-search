import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SCRIPT = REPO_ROOT / "tools" / "security_guards.py"

sys.path.insert(0, str(REPO_ROOT / "tools"))
import security_guards  # noqa: E402  (imported for its allowlist constants)


def run_guards(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "security_guards.py")],
        capture_output=True,
        text=True,
    )


def toml_allow(entries: list[str]) -> str:
    lines = ["[permission]", "allow = ["]
    for entry in entries:
        lines.append(f'  "{entry}",')
    lines.append("]")
    return "\n".join(lines) + "\n"


class GuardRepoFixture(unittest.TestCase):
    """Builds a minimal repo tree the guards pass on, then breaks one thing per test.

    The guard script resolves the repo root from its own location, so each test
    copies it into a temp tree and runs it as a subprocess - the same way CI
    invokes it - asserting on real exit codes and messages.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        (self.root / "tools").mkdir()
        shutil.copy(GUARD_SCRIPT, self.root / "tools" / "security_guards.py")

        self.config = self.root / ".grok" / "config.toml"
        self.config.parent.mkdir()
        self.write_config(sorted(security_guards.ALLOWED_PERMISSIONS))

        self.gitignore = self.root / ".gitignore"
        self.write_gitignore(security_guards.REQUIRED_IGNORE_RULES)

        self.manifest = self.root / ".agents" / "skills" / "example-search" / "cli" / "package.json"
        self.manifest.parent.mkdir(parents=True)
        self.write_manifest({"name": "example-cli", "scripts": {"start": "bun run src/cli.ts"}})

    def write_config(self, allow):
        if isinstance(allow, str):
            self.config.write_text(allow)
        else:
            self.config.write_text(toml_allow(list(allow)))

    def write_gitignore(self, rules):
        self.gitignore.write_text("\n".join(rules) + "\n")

    def write_manifest(self, data, path=None):
        (path or self.manifest).write_text(
            __import__("json").dumps(data)
        )


class CleanTreeTests(GuardRepoFixture):
    def test_clean_tree_passes(self):
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("security_guards: OK", result.stdout)


class PermissionGuardTests(GuardRepoFixture):
    def test_wildcard_bash_permission_fails(self):
        self.write_config(sorted(security_guards.ALLOWED_PERMISSIONS) + ["Bash(*)"])
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not in the reviewed allowlist", result.stdout)
        self.assertIn("Bash(*)", result.stdout)

    def test_network_fetch_permission_fails(self):
        self.write_config(sorted(security_guards.ALLOWED_PERMISSIONS) + ["Bash(curl *)"])
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not in the reviewed allowlist", result.stdout)

    def test_dropped_allowlisted_permission_still_passes(self):
        # Removing a shipped permission narrows exposure; the guard only
        # rejects additions, it must not force entries to exist.
        allow = sorted(security_guards.ALLOWED_PERMISSIONS)[:-1]
        self.write_config(allow)
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_config_toml_fails(self):
        self.config.write_text("[[[not toml")
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid TOML", result.stdout)

    def test_malformed_config_shape_fails_cleanly(self):
        for text, message in [
            ('permission = []\n', "permission must be a table"),
            ('[permission]\nallow = "Bash(*)"\n', "permission.allow must be a list of strings"),
            ('[permission]\nallow = [1]\n', "permission.allow must be a list of strings"),
        ]:
            with self.subTest(text=text):
                self.write_config(text)
                result = run_guards(self.root)
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stdout)
                self.assertNotIn("Traceback", result.stderr)


class GitignoreGuardTests(GuardRepoFixture):
    def test_each_missing_personal_data_rule_fails(self):
        for rule in security_guards.REQUIRED_IGNORE_RULES:
            with self.subTest(rule=rule):
                remaining = [r for r in security_guards.REQUIRED_IGNORE_RULES if r != rule]
                self.write_gitignore(remaining)
                result = run_guards(self.root)
                self.assertEqual(result.returncode, 1)
                self.assertIn("required personal-data rule missing", result.stdout)
                self.assertIn(rule, result.stdout)
        self.write_gitignore(security_guards.REQUIRED_IGNORE_RULES)

    def test_extra_rules_are_allowed(self):
        self.write_gitignore(list(security_guards.REQUIRED_IGNORE_RULES) + ["*.bak", "scratch/"])
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class GitignoreNegationTests(GuardRepoFixture):
    def test_negation_reincluding_personal_data_fails(self):
        rules = list(security_guards.REQUIRED_IGNORE_RULES) + ["!salary_data.json"]
        self.write_gitignore(rules)
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("negation rule not in the reviewed allowlist", result.stdout)
        self.assertIn("!salary_data.json", result.stdout)

    def test_allowed_negations_pass(self):
        rules = list(security_guards.REQUIRED_IGNORE_RULES) + sorted(
            security_guards.ALLOWED_IGNORE_NEGATIONS
        )
        # REQUIRED already includes !cv/main_example.tex; dedupe for a clean write
        self.write_gitignore(list(dict.fromkeys(rules)))
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class PackageManifestTests(GuardRepoFixture):
    def test_lifecycle_script_fails(self):
        self.write_manifest(
            {"name": "example-cli", "scripts": {"postinstall": "node evil.js", "start": "bun run src/cli.ts"}}
        )
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("lifecycle script", result.stdout)
        self.assertIn("postinstall", result.stdout)

    def test_trusted_dependencies_fails(self):
        self.write_manifest(
            {
                "name": "example-cli",
                "scripts": {"start": "bun run src/cli.ts"},
                "trustedDependencies": ["left-pad"],
            }
        )
        result = run_guards(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("trustedDependencies", result.stdout)


if __name__ == "__main__":
    unittest.main()
