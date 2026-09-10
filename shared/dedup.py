"""
In-memory duplicate-message guard, used by every agent (including the
Coordinator) to dedupe on task_id: if a retried AgentMessage with a
task_id we've already processed arrives, we return the cached response
instead of re-executing the action.
"""
from __future__ import annotations

import threading
from typing import Optional


class TaskDedupStore:
    def __init__(self, max_size: int = 5000):
        self._seen: dict[str, dict] = {}
        self._order: list[str] = []
        self._max_size = max_size
        self._lock = threading.Lock()

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            return self._seen.get(task_id)

    def put(self, task_id: str, response: dict) -> None:
        with self._lock:
            if task_id not in self._seen and len(self._order) >= self._max_size:
                oldest = self._order.pop(0)
                self._seen.pop(oldest, None)
            if task_id not in self._seen:
                self._order.append(task_id)
            self._seen[task_id] = response
