"""Pins the upstream identity of the Ethen Code fork: license, brand text, CLI entry points and the reviewed UI files must not drift.

Pure file checks (no network, no model, no git needed), so they run in any snapshot of the repository.
"""

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
