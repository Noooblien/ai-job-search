#!/usr/bin/env python3
"""Lint the repo's skill, command, and Grok config files.

Run from anywhere: python tools/lint_skills.py

Checks:
- Every SKILL.md (.grok/skills/*, .agents/skills/*) has YAML frontmatter that
  parses, with non-empty `name` and `description` keys
- `allowed-tools` entries of the form `Bash(bun run <path> *)` point at files
  that exist (skill paths resolve relative to the repo root and to .agents/)
- Every .grok/commands/*.md starts with a `# /<name>` title
- .grok/config.toml has a [permission].allow list of strings

Exit code 0 on success, 1 with a failure list otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("lint_skills.py requires PyYAML: pip install pyyaml")

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10
    tomllib = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    # Minimal fallback for Python 3.10: only what this repo needs.
    if re.search(r"\[{3,}", text):
        raise ValueError("invalid TOML")
    if re.search(r"^\s*permission\s*=", text, re.M) and "[permission]" not in text:
        raise ValueError("expected [permission] to be a table")
    m = re.search(r"\[permission\](.*?)(?:\n\[|\Z)", text, re.S)
    if not m:
        return {}
    body = m.group(1)
    bracket = re.search(r"allow\s*=\s*\[", body)
    if re.search(r"allow\s*=\s*\"", body) and not bracket:
        raise ValueError("permission.allow must be a list of strings")
    if re.search(r"allow\s*=\s*\[\s*\d", body):
        raise ValueError("permission.allow must be a list of strings")
    allow_m = re.search(r"allow\s*=\s*\[(.*?)\]", body, re.S)
    if not allow_m:
        return {"permission": {}}
    entries = re.findall(r'"([^"]*)"', allow_m.group(1))
    return {"permission": {"allow": entries}}


def check_skill(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append(f"{rel(path)}: missing YAML frontmatter (file must start with ---)")
        return
    end = text.find("\n---", 4)
    if end == -1:
        errors.append(f"{rel(path)}: unterminated YAML frontmatter")
        return
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        errors.append(f"{rel(path)}: frontmatter is not valid YAML: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel(path)}: frontmatter did not parse to a mapping")
        return
    for key in ("name", "description"):
        if not data.get(key):
            errors.append(f"{rel(path)}: frontmatter missing required key '{key}'")

    allowed = data.get("allowed-tools", "")
    if isinstance(allowed, str):
        for match in re.finditer(r"bun run ([^\s)]+)", allowed):
            target = match.group(1).rstrip("*")
            if not target or target.endswith("/"):
                continue
            # Targets may contain globs (e.g. .agents/skills/*/cli/src/cli.ts);
            # require at least one existing file to match.
            if "*" in target:
                if not list(ROOT.glob(target)) and not list((ROOT / ".agents").glob(target)):
                    errors.append(f"{rel(path)}: allowed-tools glob matches no files: {target}")
            else:
                candidates = [ROOT / target, ROOT / ".agents" / target]
                if not any(c.is_file() for c in candidates):
                    errors.append(f"{rel(path)}: allowed-tools references a missing file: {target}")


def check_command(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").lstrip().splitlines()
    first = lines[0] if lines else ""
    if not first.startswith("# /"):
        errors.append(
            f"{rel(path)}: command file must start with a '# /<name>' title (found: {first[:50]!r})"
        )


def check_config() -> None:
    path = ROOT / ".grok" / "config.toml"
    try:
        data = load_toml(path)
    except OSError as exc:
        errors.append(f".grok/config.toml: {exc}")
        return
    except Exception as exc:  # TOMLDecodeError on 3.11+, ValueError on fallback
        errors.append(f".grok/config.toml: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(".grok/config.toml: expected top-level TOML table")
        return
    permission = data.get("permission", {})
    if not isinstance(permission, dict):
        errors.append(".grok/config.toml: expected [permission] to be a table")
        return
    allow = permission.get("allow")
    if not isinstance(allow, list) or not all(isinstance(entry, str) for entry in allow):
        errors.append(".grok/config.toml: expected permission.allow to be a list of strings")


def main() -> int:
    skills = sorted(ROOT.glob(".grok/skills/*/SKILL.md")) + sorted(
        ROOT.glob(".agents/skills/*/SKILL.md")
    )
    commands = sorted((ROOT / ".grok" / "commands").glob("*.md"))
    if not skills:
        errors.append("no SKILL.md files found - glob roots are wrong or the tree moved")
    if not commands:
        errors.append("no command files found under .grok/commands/")

    for skill in skills:
        check_skill(skill)
    for command in commands:
        check_command(command)
    check_config()

    if errors:
        print(f"lint_skills: {len(errors)} failure(s)")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"lint_skills: OK ({len(skills)} skills, {len(commands)} commands, config.toml)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
