"""task_manager.py — Manages the running state of the request scheduler."""

import asyncio
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class SchedulerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class TaskManager:
    """Thread-safe task state manager for the request scheduler."""

    def __init__(self):
        self._state = SchedulerState.IDLE
        self._cancel_event: Optional[asyncio.Event] = None
        self._current_target: str = ""
        self._attack_type: str = "sms"  # sms, call, email
        self._delay: float = 2.0
        self._total_sent: int = 0
        self._total_failed: int = 0
        self._current_endpoint: str = ""

    @property
    def state(self) -> SchedulerState:
        return self._state

    @state.setter
    def state(self, value: SchedulerState):
        self._state = value

    @property
    def current_target(self) -> str:
        return self._current_target

    @current_target.setter
    def current_target(self, value: str):
        self._current_target = value

    @property
    def attack_type(self) -> str:
        return self._attack_type

    @attack_type.setter
    def attack_type(self, value: str):
        self._attack_type = value

    @property
    def delay(self) -> float:
        return self._delay

    @delay.setter
    def delay(self, value: float):
        self._delay = max(0.1, value)

    @property
    def total_sent(self) -> int:
        return self._total_sent

    @property
    def total_failed(self) -> int:
        return self._total_failed

    @property
    def current_endpoint(self) -> str:
        return self._current_endpoint

    @current_endpoint.setter
    def current_endpoint(self, value: str):
        self._current_endpoint = value

    async def get_cancel_event(self) -> asyncio.Event:
        if self._cancel_event is None:
            self._cancel_event = asyncio.Event()
        return self._cancel_event

    async def reset_cancel_event(self):
        self._cancel_event = asyncio.Event()

    def increment_sent(self):
        self._total_sent += 1

    def increment_failed(self, count: int = 1):
        self._total_failed += count

    def reset_counters(self):
        self._total_sent = 0
        self._total_failed = 0

    def get_status_dict(self) -> dict:
        return {
            "state": self._state.value,
            "target": self._current_target,
            "attack_type": self._attack_type,
            "delay": self._delay,
            "total_sent": self._total_sent,
            "total_failed": self._total_failed,
            "current_endpoint": self._current_endpoint,
        }
