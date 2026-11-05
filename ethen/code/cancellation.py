"""Operator cancellation bridge for one isolated native Hermes worker."""
from __future__ import annotations

import queue
import signal
import threading
import logging


class NativeCancellation:
    def __init__(self, agent, boundary, route):
        self.agent, self.boundary, self.route = agent, boundary, route
        self.commands: queue.Queue = queue.Queue()
        self.cancelled = threading.Event()
        from agent.memory_provider import spawn_context_thread
        self.thread = spawn_context_thread(self._watch, name='owned-native-cancellation')
        self.previous = None
        self.error = None

    def start(self):
        self.previous = signal.signal(signal.SIGTERM, self._signal)
        self.thread.start()

    def _signal(self, signum, frame):
        self.commands.put('cancel')

    def _watch(self):
        from tools.terminal_tool import cleanup_all_environments
        if self.commands.get() != 'cancel':
            return
        self.cancelled.set()
        self.boundary.cancel()
        self.route.cancel()
        try:
            self.agent.interrupt('Owned operator cancellation', hard_cancel=True)
            cleanup_all_environments()
        except Exception as exc:
            logging.getLogger(__name__).exception("Native cancellation cleanup failed")
            self.error = exc

    def close(self):
        self.commands.put('shutdown')
        self.thread.join(timeout=20)
        signal.signal(signal.SIGTERM, self.previous)
        if self.thread.is_alive() or self.error is not None:
            raise RuntimeError('Native cancellation cleanup did not finish') from self.error
