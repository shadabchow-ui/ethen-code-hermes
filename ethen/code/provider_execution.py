"""Durable per-request budget enforcement for native Hermes LLM middleware.

Permission failures terminate this owned worker rather than entering the native
plugin framework's fail-open exception path. No provider fallback is attempted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, UTC
from decimal import Decimal
from threading import Lock

from ethen.code.routing import BudgetLedger, Lane


class RouteStopped(BaseException):
    """Deliberate worker-stop signal, not a recoverable observer-hook error."""


class BoundedProvider:
    def __init__(self, ledger: BudgetLedger, lane: Lane, task: str,
                 task_tokens: int, task_cost: Decimal, daily_cost: Decimal,
                 output_tokens: int, available, attempts: int = 14, *, provider: str | None = None,
                 base_url: str | None = None):
        if type(output_tokens) is not int or output_tokens <= 0:
            raise ValueError('Positive output ceiling required')
        self.ledger, self.lane, self.task = ledger, lane, task
        self.task_tokens, self.task_cost, self.daily_cost = task_tokens, task_cost, daily_cost
        self.output_tokens, self.available, self.attempts = output_tokens, available, attempts
        self.provider, self.base_url = provider, base_url
        self.sequence = 0
        self.cancelled = False
        self.lock = Lock()
        self.receipts: list[dict] = []

    def cancel(self) -> None:
        with self.lock:
            self.cancelled = True

    def __call__(self, request, next_call, **context):
        with self.lock:
            try:
                if self.cancelled or self.sequence >= self.attempts:
                    raise PermissionError('Cancelled or provider attempt ceiling reached')
                if (not self.provider or not self.base_url or context.get('provider') != self.provider
                        or str(context.get('base_url', '')).rstrip('/') != self.base_url.rstrip('/')):
                    raise PermissionError('Unapproved provider or origin; fallback forbidden')
                if request.get('model') != self.lane.model or not self.available():
                    raise PermissionError('Unauthorized model or unavailable provider')
                estimate = token_ceiling(request, self.output_tokens)
                self.sequence += 1
                identifier = self.task + ':provider:' + str(self.sequence)
                receipt = self.ledger.reserve(identifier, self.task,
                                              datetime.now(UTC).date().isoformat(),
                                              self.lane, estimate, self.task_tokens,
                                              self.task_cost, self.daily_cost)
            except Exception as exc:
                raise RouteStopped('Provider dispatch denied before I/O') from exc
        try:
            result = next_call(request)
        except Exception as exc:
            fault = getattr(exc, 'original', exc)  # Native middleware wraps downstream SDK errors.
            state = 'rate_limited' if getattr(fault, 'status_code', None) == 429 else 'failed'
            if isinstance(fault, TimeoutError) or 'Timeout' in type(fault).__name__:
                state = 'timeout'
            self.ledger.finish(identifier, state)
            receipt['state'] = state
            self.receipts.append(receipt)
            raise
        with self.lock:
            if self.cancelled:
                self.ledger.finish(identifier, 'cancelled')
                receipt['state'] = 'cancelled'
                self.receipts.append(receipt)
                raise RouteStopped('Cancelled provider result discarded')
            self.ledger.finish(identifier, 'completed')
            receipt['state'] = 'completed'
            usage = getattr(result, 'usage', None)
            receipt['provider_reported_usage'] = (usage.model_dump() if hasattr(usage, 'model_dump')
                                                 else usage if isinstance(usage, dict) else None)
            receipt['actual_billed_cost'] = None
            receipt['usage_kind'] = 'SYNTHETIC_PROVIDER_REPORT' if self.lane.synthetic else 'PROVIDER_REPORT'
            self.receipts.append(receipt)
            return result


def loopback_available(url: str) -> bool:
    """Bounded availability probe of the owned synthetic transport, never DNS/cloud."""
    import socket
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port is None:
        return False
    try:
        with socket.create_connection(('127.0.0.1', parsed.port), timeout=1):
            return True
    except OSError:
        return False


def token_ceiling(request: dict, limit: int) -> int:
    if type(request.get('n', 1)) is not int or request.get('n', 1) != 1:
        raise PermissionError('Multiple-generation pricing is not authorized')
    for message in request.get('messages', []):
        content = message.get('content')
        if isinstance(content, list) and any(block.get('type') not in {'text', 'input_text'} for block in content):
            raise PermissionError('Nontext token pricing is not authorized')
    outputs = [request[k] for k in ('max_tokens', 'max_completion_tokens', 'max_output_tokens')
               if k in request]
    if len(outputs) != 1 or type(outputs[0]) is not int or not 0 < outputs[0] <= limit:
        raise PermissionError('Missing or excessive output token ceiling')
    # UTF-8 bytes conservatively bound token count for this JSON/text-only consumer.
    return len(json.dumps(request, ensure_ascii=False).encode('utf8')) + outputs[0]
