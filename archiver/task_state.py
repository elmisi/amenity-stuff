from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TaskState:
    running: bool = False
    worker: Optional[Any] = None
    cancel_requested: bool = False

    def start(self, worker: Any) -> None:
        self.running = True
        self.worker = worker
        self.cancel_requested = False

    def finish(self) -> None:
        self.running = False
        self.worker = None
        self.cancel_requested = False

    def request_cancel(self) -> None:
        self.cancel_requested = True
        if self.worker is None:
            return
        try:
            self.worker.cancel()
        except Exception:
            pass

