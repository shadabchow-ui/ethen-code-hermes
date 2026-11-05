"""Public, synthetic-only qualification of the unchanged Hermes coding runtime.

This is an offline test consumer, not a production agent service or a sandbox.
Run it only in the disposable OS confinement described in README.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

BEFORE = "def add(a, b):\n    return a - b\n"
AFTER = "def add(a, b):\n    return a + b\n"
TESTS = """import unittest
from calc import add
class Addition(unittest.TestCase):
    def test_positive(self): self.assertEqual(add(2, 3), 5)
    def test_negative(self): self.assertEqual(add(-2, -3), -5)
    def test_zero(self): self.assertEqual(add(7, 0), 7)
"""


def require_synthetic_route(url: str, model: str, spend_limit: int) -> None:
    """No external hosts, credentials, real model IDs or spending authorization."""
    parsed = urlsplit(url)
    if not (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port is not None
        and 1024 <= parsed.port <= 65535
        and parsed.path in ("", "/v1")
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and model == "fake-model"
        and type(spend_limit) is int
        and spend_limit == 0
    ):
        raise ValueError(
            "Only the owned synthetic loopback route with zero spend is allowed"
        )


class EditGrant:
    """One exact, single-use fixture edit through Hermes' native ACP gate."""

    def __init__(self, project: Path):
        self.project = project.resolve(strict=True)
        self._lock = threading.Lock()
        self.used = False
        self.cancelled = False
        self.decisions: list[dict] = []

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True

    def __call__(self, proposal) -> bool:
        with self._lock:
            path = Path(proposal.path)
            allowed = bool(
                not self.cancelled
                and not self.used
                and proposal.tool_name == "patch"
                and not path.is_symlink()
                and path.resolve() == self.project / "calc.py"
                and proposal.paths in ((), (str(self.project / "calc.py"),))
                and proposal.old_text == BEFORE
                and proposal.new_text == AFTER
            )
            self.decisions.append({"tool": proposal.tool_name, "allowed": allowed})
            if allowed:
                self.used = True
            return allowed


def _git(project: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(project),
            *args,
        ],
        text=True,
        timeout=15,
    )


def run_fixture(root: Path, outside: Path) -> dict:
    """Real agent/SDK/tool/session I/O with synthetic responses; no inference.

    ``outside`` must be an owned, nonexistent sentinel outside the kernel write
    allowlist. The kernel, not model instructions or this grant, denies shell I/O.
    """
    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise ValueError("An empty owned disposable directory is required")
    if (
        outside.exists()
        or outside.is_symlink()
        or root.resolve() in outside.resolve().parents
    ):
        raise ValueError(
            "A nonexistent owned sentinel outside the writable root is required"
        )
    isolation = require_runtime_isolation(outside)
    (root / "runtime-boundary.json").write_text(json.dumps(isolation, indent=2))
    home = root / "home"
    project = root / "project"
    home.mkdir()
    project.mkdir()
    (project / "calc.py").write_text(BEFORE)
    (project / "test_calc.py").write_text(TESTS)
    _git(project, "init", "-q")
    _git(project, "add", "calc.py", "test_calc.py")
    _git(
        project,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "owned synthetic baseline",
    )
    # Set before importing native modules, which resolve profile paths at import.
    prior = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "TERMINAL_CWD", "TERMINAL_ENV")
    }
    os.environ.update(
        HERMES_HOME=str(home), TERMINAL_CWD=str(project), TERMINAL_ENV="local"
    )
    try:
        return _run_native(root, outside, home, project)
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def require_runtime_isolation(outside: Path) -> dict:
    """Refuse to run the agent without the qualification's kernel restrictions."""
    status = Path("/proc/self/status").read_text()
    routes = Path("/proc/net/route").read_text().splitlines()
    devices = Path("/proc/net/dev").read_text().splitlines()[2:]
    if (
        "NoNewPrivs:\t1" not in status
        or len(routes) != 1
        or any(line.split(":", 1)[0].strip() != "lo" for line in devices)
    ):
        raise ValueError(
            "A no-new-privileges, loopback-only Linux namespace is required"
        )
    group = Path("/proc/self/cgroup").read_text().strip().split(":")[-1]
    cgroup = Path("/sys/fs/cgroup") / group.lstrip("/")
    limits = {
        name: (cgroup / name).read_text().strip()
        for name in ("memory.max", "memory.swap.max", "cpu.max")
    }
    quota, period = limits["cpu.max"].split()
    if (
        limits["memory.max"] == "max"
        or int(limits["memory.max"]) > 2200 * 1024**2
        or limits["memory.swap.max"] != "0"
        or quota == "max"
        or int(quota) > 2 * int(period)
    ):
        raise ValueError("A kernel memory/swap limit and at most two CPUs are required")
    try:
        fd = os.open(outside, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except PermissionError:
        return {
            "no_new_privileges": True,
            "network": "loopback-only",
            "outside_write": "DENIED",
            "limits": limits,
        }
    else:
        os.close(fd)
        outside.unlink()
        raise ValueError("The owned outside sentinel is not kernel write-confined")


def _run_native(root: Path, outside: Path, home: Path, project: Path) -> dict:
    import shlex

    from acp_adapter.edit_approval import (
        reset_edit_approval_requester,
        set_edit_approval_requester,
    )
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from tests.fakes.fake_llm_provider import (
        FakeLLMServer,
        Text,
        ToolCall,
        write_hermes_home,
    )
    from tools.terminal_tool import cleanup_all_environments

    script = [
        ToolCall("read_file", {"path": str(project / "calc.py")}),
        ToolCall(
            "terminal",
            {
                "command": "python3 -B -m unittest -v test_calc",
                "workdir": str(project),
                "timeout": 20,
            },
        ),
        ToolCall(
            "write_file",
            {
                "path": str(project / "test_calc.py"),
                "content": "# unauthorized test deletion\n",
            },
        ),
        ToolCall(
            "patch",
            {
                "path": str(project / "calc.py"),
                "old_string": "return a - b",
                "new_string": "return a + b",
            },
        ),
        ToolCall(
            "terminal",
            {
                "command": "python3 -B -m unittest -v test_calc",
                "workdir": str(project),
                "timeout": 20,
            },
        ),
        ToolCall(
            "terminal",
            {
                "command": "git diff --check && git diff -- calc.py && git diff --name-only",
                "workdir": str(project),
                "timeout": 20,
            },
        ),
        ToolCall(
            "terminal",
            {
                "command": "printf forbidden > " + shlex.quote(str(outside)),
                "workdir": str(project),
                "timeout": 20,
            },
        ),
        Text("SYNTHETIC coding qualification finished; no model inference."),
    ]
    grant = EditGrant(project)
    token = set_edit_approval_requester(grant)
    session_id = "ethen-owned-coding-qualification"
    db_path = home / "qualification.db"
    db = SessionDB(db_path=db_path)
    try:
        with FakeLLMServer(script) as server:
            require_synthetic_route(server.base_url, "fake-model", 0)
            write_hermes_home(
                home,
                server.base_url,
                extra_config=(
                    "updates:\n  check: false\nmodels_dev:\n  url: http://127.0.0.1:9/api.json\n"
                    "skills:\n  creation_nudge_interval: 0\nmemory:\n  nudge_interval: 0\n"
                ),
            )
            agent = AIAgent(
                provider="custom",
                base_url=server.base_url,
                api_key="sk-fake-e2e",
                model="fake-model",
                max_iterations=12,
                run_budget_seconds=90,
                enabled_toolsets=["terminal", "file"],
                quiet_mode=True,
                skip_memory=True,
                skip_context_files=True,
                skip_background_review=True,
                session_id=session_id,
                session_db=db,
                cwd=str(project),
            )
            try:
                result = agent.run_conversation(
                    "Synthetic qualification: fix add, test, and review only the authorized edit.",
                    conversation_history=[],
                    task_id=session_id,
                )
            finally:
                agent.close()
            requests = server.main_requests()
            replies = [m for m in requests[-1]["messages"] if m.get("role") == "tool"]
            if not result.get("completed") or len(requests) != 8 or len(replies) != 7:
                raise RuntimeError(
                    "Native coding workflow did not finish its bounded script"
                )
            parsed = [json.loads(reply["content"]) for reply in replies]
            if grant.decisions != [
                {"tool": "write_file", "allowed": False},
                {"tool": "patch", "allowed": True},
            ]:
                raise RuntimeError("Native ACP did not enforce the exact fixture grant")
            if (
                parsed[1].get("exit_code") != 1
                or not parsed[2].get("error")
                or parsed[4].get("exit_code") != 0
                or parsed[5].get("exit_code") != 0
                or parsed[6].get("exit_code") in (None, 0)
            ):
                raise RuntimeError(
                    "Native test, approval, diff or OS denial check failed"
                )
            if outside.exists() or (project / "test_calc.py").read_text() != TESTS:
                raise RuntimeError("Unauthorized write reached a fixture endpoint")
            if (project / "calc.py").read_text() != AFTER or _git(
                project, "diff", "--name-only"
            ).strip() != "calc.py":
                raise RuntimeError("Controlled diff mismatch")
            transcript = {
                "requests": requests,
                "result": result,
                "tool_replies": parsed,
            }
            raw = json.dumps(transcript, sort_keys=True, default=str).encode()
            (root / "transcript.json").write_bytes(raw)
    finally:
        reset_edit_approval_requester(token)
        db.close()
        cleanup_all_environments()
    # A fresh native connection, not an in-memory history stub.
    recovered = SessionDB(db_path=db_path)
    try:
        history, display = recovered.get_resume_conversations(session_id)
        if not any(row.get("role") == "tool" for row in history):
            raise RuntimeError("Native session restart recovery failed")
    finally:
        recovered.close()
    receipt = {
        "schema": 1,
        "foundation": "NousResearch/hermes-agent",
        "model_execution": "SYNTHETIC_UNVERIFIED",
        "external_model_calls": 0,
        "paid_spend_authorized": 0,
        "real_native_agent_loop": True,
        "http_fixture_requests": len(requests),
        "native_tool_calls": len(replies),
        "red_test_exit": 1,
        "green_test_exit": 0,
        "diff_exit": 0,
        "changed_files": ["calc.py"],
        "edit_decisions": grant.decisions,
        "unauthorized_file_write_denied": True,
        "unauthorized_terminal_write_denied": True,
        "session_restart_recovered": True,
        "history_messages": len(history),
        "display_messages": len(display),
        "transcript_sha256": hashlib.sha256(raw).hexdigest(),
        "production_coding_service": "NOT_QUALIFIED; EV6-045/046 required",
    }
    (root / "review-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
