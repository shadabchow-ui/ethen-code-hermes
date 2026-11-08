"""Pins the upstream identity of the Ethen Code fork: license, brand text, CLI entry points and the reviewed UI files must not drift.

Pure file checks (no network, no model, no git needed), so they run in any snapshot of the repository.
"""

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Second anchor, deliberately outside the pin file: changing a pin value alone must fail; re-pinning needs a reviewed change to this file too.
BASE_COMMIT = "5e7c2b254d414e4e25105231f818f385fee67469"
UI_PR_1_COMMIT = "bdeda596ab6ee7f503992294605a3e3087049646"
PINS = json.loads((ROOT / "ethen" / "code" / "UPSTREAM_PINS.json").read_text())


def _sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def test_pin_file_declares_hermes_as_the_only_runtime_foundation():
    assert PINS["schema"] == "ethen.code.upstream-pins/1"
    assert PINS["job"] == "EV6-044"
    assert "sole Ethen Code runtime foundation" in PINS["decision"]
    hermes = PINS["hermes"]
    assert hermes["license"] == "MIT"
    assert hermes["upstream"] == "https://github.com/NousResearch/hermes-agent"
    for key in ("pinned_base_commit", "ui_pr_1_commit", "qualification_commit", "preserved_source_commit"):
        assert re.fullmatch(r"[0-9a-f]{40}", hermes[key]), key
    assert hermes["fork_main_equals_pinned_base"] is True
    assert hermes["pinned_base_commit"] == BASE_COMMIT
    assert hermes["ui_pr_1_commit"] == UI_PR_1_COMMIT
    assert PINS["hermes"]["pinned_base_date"] == "2026-11-02"
    assert BASE_COMMIT in PINS["hermes"]["ancestry_check"] and "ancestor" in PINS["hermes"]["ancestry_check"]


def test_opencode_is_recorded_as_an_unchanged_archive_without_a_dependency():
    oc = PINS["opencode"]
    assert oc["status"].startswith("ARCHIVE_UNCHANGED")
    assert "Nothing in this repository imports or depends on it" in oc["note"]
    # no runtime, adapter or dependency on the archived repository
    pyproject = (ROOT / "pyproject.toml").read_text().lower()
    assert "ethen-code-oc" not in pyproject and "opencode" not in pyproject


def test_unchanged_upstream_files_keep_their_exact_content():
    for rel, want in PINS["unchanged_from_pinned_base"]["files"].items():
        assert _sha256(rel) == want, f"{rel} drifted from the pinned upstream content"


def test_the_upstream_mit_license_and_copyright_notice_are_intact():
    text = (ROOT / "LICENSE").read_text()
    assert text.startswith("MIT License")
    assert "Copyright (c) 2025 Nous Research" in text
    assert "Permission is hereby granted, free of charge" in text
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in text


def test_cli_entry_points_are_the_upstream_hermes_ones():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts == PINS["unchanged_from_pinned_base"]["cli_entry_points"]


def test_the_reviewed_foundation_ui_files_are_byte_identical_to_pr_1():
    for rel, want in PINS["ethen_foundation_ui_pr_1"]["files"].items():
        assert _sha256(rel) == want, f"{rel} drifted from UI PR #1"


def _tracked_license_files():
    import re
    import subprocess

    try:
        names = subprocess.check_output(["git", "-C", str(ROOT), "ls-files"], text=True, stderr=subprocess.DEVNULL).splitlines()
    except Exception:  # an exported snapshot has no .git: fall back to a filesystem walk
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts]
    return sorted(n for n in names if re.search(r"(^|/)(LICENSE|COPYING|NOTICE)(\.[A-Za-z]+)?$", n))


def test_every_license_and_notice_file_is_pinned_and_none_added_or_removed():
    pinned = PINS["license_and_notice_files"]["files"]
    assert _tracked_license_files() == sorted(pinned)
    for rel, want in pinned.items():
        assert _sha256(rel) == want, f"{rel} drifted"


def test_the_deploy_disabling_vercel_json_files_are_all_present_and_unchanged():
    pinned = PINS["deploy_disabled_vercel_json"]["files"]
    assert len(pinned) == 12
    for rel, want in pinned.items():
        assert _sha256(rel) == want, f"{rel} drifted"


def test_the_workspace_manifest_is_unchanged():
    for rel, want in PINS["workspace_manifest"]["files"].items():
        assert _sha256(rel) == want
    assert json.loads((ROOT / "package.json").read_text())["workspaces"] == ["apps/*", "ui-tui", "ui-tui/packages/*", "web", "tests-js"]


def test_each_cli_entry_point_target_exists_and_defines_its_function():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    for name, target in scripts.items():
        module, func = target.split(":")
        path = ROOT / (module.replace(".", "/") + ".py")
        assert path.is_file(), f"{name}: {path} missing"
        assert re.search(rf"^def {re.escape(func)}\(", path.read_text(), re.M), f"{name}: {func} not defined in {path}"
    for rel in PINS["entry_point_files"]:
        assert (ROOT / rel).is_file()


def test_no_python_or_dependency_file_imports_or_requires_opencode():
    pattern = re.compile(r"^\s*(import|from)\s+opencode\b|ethen-code-oc", re.M)  # statements only: upstream comments may mention OpenCode in prose
    here = Path(__file__).resolve()
    skip = {"node_modules", ".git", "venv", ".venv"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or skip & set(path.relative_to(ROOT).parts) or path.resolve() == here or path.name == "UPSTREAM_PINS.json":
            continue
        if path.suffix in (".py", ".toml", ".txt", ".cfg") or path.name in ("uv.lock", "package.json"):
            assert not pattern.search(path.read_text(errors="ignore")), f"OpenCode reference in {path}"
