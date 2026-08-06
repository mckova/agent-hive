from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_hive.mission import validate_mission

JSON_FILES = [
    ".claude-plugin/marketplace.json", "plugins/codex/agent-hive/.codex-plugin/plugin.json",
    "plugins/claude-code/agent-hive/.claude-plugin/plugin.json", "schemas/mission.schema.json",
    "schemas/run.schema.json", "schemas/usage.schema.json", "examples/missions/japanese-release.json",
    "examples/missions/arabic-api.json", "examples/missions/french-gated-deploy.json",
    "examples/missions/spanish-migration.json",
]
ATTRIBUTION = "Copyright (c) 2026 May Sidon | Agent Hive | https://github.com/mckova/agent-hive"


def main() -> int:
    parsed = {name: json.loads((ROOT / name).read_text(encoding="utf-8")) for name in JSON_FILES}
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    assert parsed["plugins/codex/agent-hive/.codex-plugin/plugin.json"]["version"] == version, "Codex plugin version differs from pyproject.toml."
    assert parsed["plugins/claude-code/agent-hive/.claude-plugin/plugin.json"]["version"] == version, "Claude plugin version differs from pyproject.toml."
    assert parsed[".claude-plugin/marketplace.json"]["plugins"][0]["version"] == version, "Claude marketplace version differs from pyproject.toml."
    assert project["authors"][0]["name"] == "May Sidon", "Project author differs from the copyright holder."
    assert project["license"] == "MIT", "Project license must use the MIT SPDX identifier."
    for name in ("LICENSE", "NOTICE", "README.md"):
        assert ATTRIBUTION in (ROOT / name).read_text(encoding="utf-8"), f"{name} is missing the copyright notice."
    for name in JSON_FILES:
        if name.startswith("examples/missions/"):
            assert not validate_mission(parsed[name]), f"Invalid example mission: {name}"

    skills = [ROOT / "plugins" / platform / "agent-hive" / "skills" / "run-agent-hive" / "SKILL.md"
              for platform in ("codex", "claude-code")]
    for path in skills:
        contents = path.read_text(encoding="utf-8")
        assert contents.startswith("---\n"), f"Missing skill frontmatter: {path}"
        assert "[TODO:" not in contents, f"Skill contains TODO: {path}"
    metadata = (ROOT / "plugins/codex/agent-hive/skills/run-agent-hive/agents/openai.yaml").read_text(encoding="utf-8")
    assert "$run-agent-hive" in metadata, "Codex UI metadata must invoke $run-agent-hive."

    expected_agents = {"hive-read-economy.md": "haiku", "hive-read-balanced.md": "sonnet", "hive-read-frontier.md": "opus",
                       "hive-write-economy.md": "haiku", "hive-write-balanced.md": "sonnet", "hive-write-frontier.md": "opus"}
    agents = ROOT / "plugins/claude-code/agent-hive/agents"
    assert {path.name for path in agents.glob("*.md")} == set(expected_agents), "Claude tier workers differ from the expected matrix."
    for name, model in expected_agents.items():
        contents = (agents / name).read_text(encoding="utf-8")
        assert re.search(rf"^model: {model}$", contents, re.M), f"{name} does not use {model}."
        if name.startswith("hive-read-"):
            assert re.search(r"^disallowedTools: .*Write.*Edit$", contents, re.M), f"{name} must remain read-only."

    source_files = sorted(path.relative_to(ROOT / "src" / "agent_hive") for path in (ROOT / "src" / "agent_hive").rglob("*.py"))
    for platform in ("codex", "claude-code"):
        runtime = ROOT / "plugins" / platform / "agent-hive" / "runtime"
        for relative in source_files:
            source = (ROOT / "src" / "agent_hive" / relative).read_bytes()
            bundled = (runtime / "agent_hive" / relative).read_bytes()
            assert bundled == source, f"{platform} Python runtime is stale: {relative.as_posix()}"
        assert (runtime / "hive.py").is_file(), f"{platform} runtime entry point is missing."

    ignored_trees = {".git", ".hive", ".venv", "__pycache__", "tmp"}
    stale = [path for path in ROOT.rglob("*") if path.suffix.lower() in {".js", ".mjs", ".cjs"}
             and not any(part in ignored_trees for part in path.relative_to(ROOT).parts)]
    assert not stale, "JavaScript files remain after the Python migration: " + ", ".join(str(path.relative_to(ROOT)) for path in stale)
    assert not (ROOT / "package.json").exists(), "Node package.json remains after the Python migration."
    _validate_markdown_links()
    print("Repository structure is valid.")
    return 0


def _validate_markdown_links() -> None:
    skipped = {".git", ".hive", "node_modules", "tmp", "__pycache__"}
    for markdown in ROOT.rglob("*.md"):
        if any(part in skipped for part in markdown.parts):
            continue
        contents = markdown.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\(([^)]+)\)", contents):
            raw = match.group(1).strip().strip("<>").split()[0].split("#")[0]
            if not raw or raw.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", raw, re.I):
                continue
            target = ROOT / raw.lstrip("/") if raw.startswith("/") else markdown.parent / raw
            assert target.resolve().exists(), f"Broken local Markdown link in {markdown.relative_to(ROOT)}: {raw}"


if __name__ == "__main__":
    raise SystemExit(main())
