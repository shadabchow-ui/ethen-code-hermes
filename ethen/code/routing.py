"""Explicit provider lanes with durable, conservative task/day reservations.

No provider is contacted here. A native Hermes consumer must reserve its maximum
usage before dispatch. Crashed/ambiguous reservations remain charged until an
operator reconciles them; retries never silently replenish a budget.
"""
from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Lane:
    name: str
    model: str
    input_per_million: Decimal | None
    output_per_million: Decimal | None
    approved: bool = False
    synthetic: bool = False

    def ceiling(self, tokens: int) -> Decimal:
        if type(self.approved) is not bool or not self.name or not self.model:
            raise PermissionError("Explicit lane authorization and model identity required")
        prices = (self.input_per_million, self.output_per_million)
        if not self.approved or any(p is None or not p.is_finite() or p < 0 for p in prices):
            raise PermissionError("Provider authorization and finite known prices required")
        if type(tokens) is not int or tokens <= 0:
            raise ValueError("A positive token ceiling is required")
        return Decimal(tokens) * max(prices) / Decimal(1_000_000)


class BudgetLedger:
    """SQLite transactions fence duplicate dispatch across processes and restarts."""

    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS reservations (request TEXT PRIMARY KEY, "
                       "task TEXT NOT NULL, day TEXT NOT NULL, lane TEXT NOT NULL, "
                       "model TEXT NOT NULL, tokens INTEGER NOT NULL, cost TEXT NOT NULL, "
                       "state TEXT NOT NULL)")

            db.execute("CREATE TABLE IF NOT EXISTS receipts (request TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, request: str, task: str, day: str, lane: Lane,
                tokens: int, task_tokens: int, task_cost: Decimal,
                daily_cost: Decimal) -> dict:
        if type(task_tokens) is not int or task_tokens <= 0:
            raise ValueError("A positive integer task token ceiling is required")
        cost = lane.ceiling(tokens)
        if not request or not task or not day:
            raise ValueError("Request, task and UTC accounting day required")
        if any(not x.is_finite() or x < 0 for x in (task_cost, daily_cost)):
            raise ValueError("Finite nonnegative cost ceilings required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM reservations WHERE request=?", (request,)).fetchone():
                raise PermissionError("Duplicate or ambiguous request; do not redispatch")
            rows = db.execute("SELECT task,day,tokens,cost FROM reservations").fetchall()
            used_tokens = sum(r[2] for r in rows if r[0] == task)
            used_task = sum((Decimal(r[3]) for r in rows if r[0] == task), Decimal(0))
            used_day = sum((Decimal(r[3]) for r in rows if r[1] == day), Decimal(0))
            if used_tokens + tokens > task_tokens or used_task + cost > task_cost or used_day + cost > daily_cost:
                raise PermissionError("Token or spending ceiling exhausted")
            db.execute("INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?)",
                       (request, task, day, lane.name, lane.model, tokens, str(cost), "reserved"))
            db.commit()
        return {"request": request, "lane": lane.name, "model": lane.model,
                "reserved_tokens": tokens, "reserved_cost": str(cost),
                "synthetic": lane.synthetic}

    def finish(self, request: str, state: str) -> None:
        if state not in {"completed", "cancelled", "timeout", "rate_limited", "failed"}:
            raise ValueError("Unknown terminal outcome")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("UPDATE reservations SET state=? WHERE request=? AND state='reserved'",
                                (state, request))
            if result.rowcount != 1:
                raise PermissionError("Missing, stale or already finalized request")
            db.commit()

    def complete(self, request: str, receipt: dict) -> None:
        payload = json.dumps(receipt, sort_keys=True, allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM reservations WHERE request=?", (request,)).fetchone()
            if row != ("reserved",):
                raise PermissionError("Completion requires the active reservation")
            db.execute("INSERT INTO receipts VALUES (?,?)", (request, payload))
            db.execute("UPDATE reservations SET state='completed' WHERE request=?", (request,))
            db.commit()

    def receipt(self, request: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM receipts JOIN reservations USING(request) "
                             "WHERE request=? AND state='completed'", (request,)).fetchone()
        return json.loads(row[0]) if row else None
