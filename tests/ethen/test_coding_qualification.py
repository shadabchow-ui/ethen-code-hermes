"""Owned synthetic qualification using real Hermes interfaces, no external model."""

import os
import shutil
from pathlib import Path

import pytest

from ethen.code.qualification import (
    AFTER,
    BEFORE,
    EditGrant,
    require_synthetic_route,
    run_fixture,
)


@pytest.mark.parametrize(
    "url,model,spend",
    [
        ("https://example.invalid/v1", "fake-model", 0),
        ("http://localhost:9000/v1", "fake-model", 0),
        ("http://127.0.0.1:9000/v1", "real-model", 0),
        ("http://127.0.0.1:9000/v1", "fake-model", 1),
        ("http://127.0.0.1:9000/v1", "fake-model", False),
        ("http://user:secret@127.0.0.1:9000/v1", "fake-model", 0),
        ("http://127.0.0.1:9000/v1?forward=https://example.invalid", "fake-model", 0),
    ],
)
def test_route_and_spending_fail_closed(url, model, spend):
    with pytest.raises(ValueError):
        require_synthetic_route(url, model, spend)


def test_exact_loopback_fixture_route():
    require_synthetic_route("http://127.0.0.1:19000/v1", "fake-model", 0)


def _proposal(project, **changes):
    from acp_adapter.edit_approval import EditProposal

    values = dict(
        tool_name="patch",
        path=str(project / "calc.py"),
        old_text=BEFORE,
        new_text=AFTER,
        arguments={},
        paths=(),
    )
    return EditProposal(**{**values, **changes})


def test_exact_edit_grant_denies_replay_and_other_payloads(tmp_path):
    (tmp_path / "calc.py").write_text(BEFORE)
    grant = EditGrant(tmp_path)
    for changes in (
        {"path": str(tmp_path / "test_calc.py")},
        {"new_text": "unauthorized"},
        {"old_text": "stale"},
        {"tool_name": "write_file"},
        {"paths": (str(tmp_path / "other.py"),)},
    ):
        assert grant(_proposal(tmp_path, **changes)) is False
    assert grant(_proposal(tmp_path)) is True
    assert grant(_proposal(tmp_path)) is False


def test_cancelled_grant_and_native_interrupt_prevent_transition(tmp_path):
    from tools.interrupt import run_if_not_interrupted, set_interrupt

    grant = EditGrant(tmp_path)
    grant.cancel()
    assert grant(_proposal(tmp_path)) is False
    effects = []
    set_interrupt(True)
    try:
        assert run_if_not_interrupted(lambda: effects.append("unauthorized")) is False
        assert effects == []
    finally:
        set_interrupt(False)


def test_symlink_edit_grant_denied(tmp_path):
    (tmp_path / "other.py").write_text(BEFORE)
    (tmp_path / "calc.py").symlink_to(tmp_path / "other.py")
    assert EditGrant(tmp_path)(_proposal(tmp_path)) is False


@pytest.mark.platforms("linux")
def test_actual_agent_coding_review_denial_and_restart(tmp_path):
    # Only the explicitly disposable VM snapshot is used by this qualification.
    # Source is read-only to the test under Landlock; no operator file is targeted.
    if os.environ.get("HERMES_RUN_E2E") != "1":
        pytest.skip(
            "Requires the approved loopback-only, write-confined qualification launcher"
        )
    root = tmp_path / "owned-session"
    root.mkdir()
    outside = Path(__file__).resolve().parents[2] / ".owned-denied-sentinel"
    receipt = run_fixture(root, outside)
    assert receipt["real_native_agent_loop"] is True
    assert receipt["unauthorized_file_write_denied"] is True
    assert receipt["unauthorized_terminal_write_denied"] is True
    assert receipt["session_restart_recovered"] is True
    assert receipt["model_execution"] == "SYNTHETIC_UNVERIFIED"
    assert receipt["external_model_calls"] == 0
    # The canonical runner removes its test roots. Preserve only owned synthetic
    # artifacts under the launcher's disposable HOME for later independent review.
    shutil.copytree(root, Path.home() / "coding-qualification-evidence")


def test_single_use_edit_grant_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    grant = EditGrant(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: grant(_proposal(tmp_path)), range(8)))
    assert outcomes.count(True) == 1
