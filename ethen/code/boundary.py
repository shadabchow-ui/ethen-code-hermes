"""Authorization layer for an isolated, single-session native Hermes consumer.

This gate supplements kernel confinement. It is not a sandbox for shell code.
"""
from __future__ import annotations

import threading
import logging

from acp_adapter.edit_approval import SENSITIVE_AUTO_APPROVE_NAMES
from pathlib import Path


class RepositoryBoundary:
    def __init__(self, root: Path, readable: set[str], edits: dict[str, tuple[str, str]],
                 commands: frozenset[str]):
        if root.is_symlink():
            raise PermissionError("Symlink workspace")
        self.root = root.resolve(strict=True)
        self.readable = frozenset(readable)
        self.edits = dict(edits)
        self.commands = commands
        self.cancelled = False
        self.used: set[str] = set()
        self.lock = threading.Lock()

    def resolve(self, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        relative = path.relative_to(self.root)
        if any(part.lower() in {"..", ".git", ".ssh"} | SENSITIVE_AUTO_APPROVE_NAMES or part.lower().startswith(".env") or
               part.lower().endswith((".pem", ".key", ".keystore")) for part in relative.parts):
            raise PermissionError("Secret or metadata path")
        cursor = self.root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise PermissionError("Symlink path")
        if not path.resolve().is_relative_to(self.root):
            raise PermissionError("Outside repository")
        return str(relative)

    def authorize(self, tool: str, args: dict) -> str | None:
        """Return a native pre-tool block directive; never throw to a soft hook."""
        with self.lock:
            try:
                self._require(tool, args)
            except Exception as exc:  # Security gate: native observer hooks otherwise fail open.
                logging.getLogger(__name__).exception("Repository authorization denied")
                return "Repository authorization denied: " + str(exc)
        return None

    def _require(self, tool: str, args: dict) -> None:
        if self.cancelled:
            raise PermissionError("Cancelled session; approvals revoked")
        if tool == "read_file":
            if self.resolve(args["path"]) not in self.readable:
                raise PermissionError("Unapproved read")
        elif tool == "terminal":
            if Path(args.get("workdir", "")).resolve() != self.root:
                raise PermissionError("Wrong terminal workspace")
            if args.get("command") not in self.commands:
                raise PermissionError("Unapproved shell command")
        elif tool == "patch":
            path = self.resolve(args["path"])
            expected = self.edits.get(path)
            if path in self.used or expected != (args.get("old_string"), args.get("new_string")):
                raise PermissionError("Stale or unapproved exact edit")
        else:
            raise PermissionError("Tool is outside the authorized workflow")

    def approve_edit(self, proposal) -> bool:
        """Bind the real native ACP edit proposal, including all affected paths."""
        with self.lock:
            try:
                path = self.resolve(proposal.path)
                if self.cancelled or proposal.tool_name != "patch" or path in self.used:
                    return False
                if proposal.paths not in ((), (str(self.root / path),)):
                    return False
                if self.edits.get(path) != (proposal.old_text, proposal.new_text):
                    return False
                self.used.add(path)
                return True
            except Exception:  # ACP permission errors must deny, never fall through.
                logging.getLogger(__name__).exception("Malformed ACP proposal denied")
                return False

    def cancel(self) -> None:
        with self.lock:
            self.cancelled = True
            self.edits.clear()
