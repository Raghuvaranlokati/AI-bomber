"""task_manager.py — Central state manager for the scheduler lifecycle."""

import asyncio
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class SchedulerState(Enum):
    """Possible states for the scheduler."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class TaskManager:
    """
    Manages scheduler state, counters, and control events.
    Provides a clean interface for starting, pausing, resuming, and stopping
    the worker loop.
    """

    def __init__(self):
        # ── State ──
        self._state = SchedulerState.IDLE

        # ── Control events ──
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()  # Not paused by default

        # ── Configuration ──
        self._target: str = ""
        self._attack_type: str = "sms"  # sms | call | email
        self._delay: float = 2.0

        # ── Counters ──
        self._total_sent: int = 0
        self._total_failed: int = 0
        self._current_endpoint: str = ""

        # ── Timing ──
        self._start_time: float = 0.0

    # ═══════════════════════════════════════════════
    # Properties
    # ═══════════════════════════════════════════════

    @property
    def state(self) -> SchedulerState:
        return self._state

    @property
    def target(self) -> str:
        return self._target

    @target.setter
    def target(self, value: str):
        self._target = value

    @property
    def attack_type(self) -> str:
        return self._attack_type

    @attack_type.setter
    def attack_type(self, value: str):
        if value not in ("sms", "call", "email"):
            raise ValueError("attack_type must be 'sms', 'call', or 'email'")
        self._attack_type = value

    @property
    def delay(self) -> float:
        return self._delay

    @delay.setter
    def delay(self, value: float):
        self._delay = max(0.1, min(30.0, value))

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

    @property
    def start_time(self) -> float:
        return self._start_time

    # ═══════════════════════════════════════════════
    # Control Events (used by worker.py)
    # ═══════════════════════════════════════════════

    @property
    def cancel_event(self) -> asyncio.Event:
        """Event that signals the worker to stop."""
        return self._cancel_event

    @property
    def pause_event(self) -> asyncio.Event:
        """
        Event that controls pause state.
        - SET (True)  = worker runs normally
        - CLEAR (False) = worker waits (paused)
        """
        return self._pause_event

    # ═══════════════════════════════════════════════
    # State Transitions
    # ═══════════════════════════════════════════════

    def prepare_start(self, target: str, attack_type: str, delay: float):
        """
        Configure and prepare for a new run.
        Resets counters, events, and sets state to IDLE (ready to start).
        """
        self._target = target
        self.attack_type = attack_type
        self.delay = delay

        # Reset counters
        self._total_sent = 0
        self._total_failed = 0
        self._current_endpoint = ""
        self._start_time = 0.0

        # Reset events
        self._cancel_event.clear()
        self._pause_event.set()

        self._state = SchedulerState.IDLE
        logger.info(
            f"Prepared: target={target}, type={attack_type}, delay={delay}s"
        )

    def start(self):
        """Transition to RUNNING state."""
        import time
        self._start_time = time.time()
        self._cancel_event.clear()
        self._pause_event.set()
        self._state = SchedulerState.RUNNING
        logger.info("Scheduler started")

    def pause(self):
        """Transition to PAUSED state. Worker will pause after current request."""
        if self._state == SchedulerState.RUNNING:
            self._pause_event.clear()
            self._state = SchedulerState.PAUSED
            logger.info("Scheduler paused")

    def resume(self):
        """Transition back to RUNNING from PAUSED."""
        if self._state == SchedulerState.PAUSED:
            self._pause_event.set()
            self._state = SchedulerState.RUNNING
            logger.info("Scheduler resumed")

    def stop(self):
        """
        Signal the worker to stop. Sets both cancel event and transitions
        to STOPPED state.
        """
        self._cancel_event.set()
        self._pause_event.set()  # Unpause so worker can read cancel
        self._state = SchedulerState.STOPPED
        logger.info("Scheduler stop signal sent")

    def reset(self):
        """Full reset to IDLE state with cleared counters."""
        self._target = ""
        self._attack_type = "sms"
        self._delay = 2.0
        self._total_sent = 0
        self._total_failed = 0
        self._current_endpoint = ""
        self._start_time = 0.0
        self._cancel_event.clear()
        self._pause_event.set()
        self._state = SchedulerState.IDLE
        logger.info("Scheduler reset to idle")

    # ═══════════════════════════════════════════════
    # Counters
    # ═══════════════════════════════════════════════

    def increment_sent(self, count: int = 1):
        """Increment the successful request counter."""
        self._total_sent += count

    def increment_failed(self, count: int = 1):
        """Increment the failed request counter."""
        self._total_failed += count

    def reset_counters(self):
        """Reset sent and failed counters to zero."""
        self._total_sent = 0
        self._total_failed = 0
        self._current_endpoint = ""
        logger.info("Counters reset")

    # ═══════════════════════════════════════════════
    # Status
    # ═══════════════════════════════════════════════

    def get_status_dict(self) -> dict:
        """Return the full status as a dictionary."""
        return {
            "state": self._state.value,
            "target": self._target,
            "attack_type": self._attack_type,
            "delay": self._delay,
            "total_sent": self._total_sent,
            "total_failed": self._total_failed,
            "current_endpoint": self._current_endpoint,
            "uptime_seconds": self._get_uptime(),
        }

    def _get_uptime(self) -> float:
        """Calculate uptime in seconds since start."""
        if self._start_time == 0.0 or self._state == SchedulerState.IDLE:
            return 0.0
        import time
        return time.time() - self._start_time