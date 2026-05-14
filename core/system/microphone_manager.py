# core/system/microphone_manager.py — JARVIS MICROPHONE LIFECYCLE MANAGER
"""
Explicit microphone ownership and lifecycle.

Problem:
  Multiple subsystems may try to open the microphone simultaneously:
    - VoiceEngine (STT / Vosk listener loop)
    - WakeWordDaemon (VAD listening)
    - VoiceInterruption (VAD during speech)
    - VoiceOutputWorker (no mic, but for completeness)

  On Windows, sounddevice/pyaudio can only be opened ONCE.
  Duplicate opens cause OSError: DeviceBusy or silent failures.

Solution:
  Centralized MicOwner enum. Only ONE subsystem holds the mic at a time.
  Contending subsystems are notified via a callback when the mic is free.

Modes:
  WAKE_WORD  — low-power VAD listening (WakeWordDaemon)
  SPEECH     — full transcription (VoiceEngine STT)
  INTERRUPT  — VAD during speech (VoiceInterruption)
  IDLE       — mic released

Rules:
  - acquire() and release() MUST be paired
  - WAKE_WORD is the lowest priority — SPEECH and INTERRUPT can pre-empt
  - IDLE means no subsystem is using the mic
  - Contention is resolved by priority: INTERRUPT > SPEECH > WAKE_WORD
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("MicManager")


class MicMode(IntEnum):
    IDLE     = 0
    WAKE_WORD= 1
    SPEECH   = 2
    INTERRUPT= 3


@dataclass
class MicOwner:
    mode: MicMode
    owner_name: str
    acquired_at: float
    thread_name: str


class MicrophoneManager:
    """
    Thread-safe microphone lifecycle manager.

    All subsystems that open the microphone MUST use this manager:
        mm = get_microphone_manager()
        token = mm.acquire(MicMode.SPEECH, "VoiceEngine")
        if token:
            # ... use mic ...
            mm.release(token)
    """

    _instance: Optional[MicrophoneManager] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._owner: Optional[MicOwner] = None
        self._contention_queue: list[tuple[MicMode, str, Callable]] = []
        self._available_callbacks: list[Callable[[], None]] = []
        self._contention_lock = threading.RLock()
        self._recovery_thread: Optional[threading.Thread] = None
        self._recovery_deadline: float = 0.0
        self._recovery_count = 0
        self._mic_dead = False
        self._lock_mode = threading.RLock()
        self._contention_sem = threading.Semaphore(3)  # max 3 concurrent notify threads

    def acquire(self, mode: MicMode, owner_name: str) -> Optional["MicToken"]:
        """
        Attempt to acquire the microphone for the given mode.

        Returns:
            MicToken if acquired, None if the mic is already held by a higher-priority owner.

        Higher priority modes can pre-empt lower ones:
            INTERRUPT > SPEECH > WAKE_WORD
        """
        with self._lock:
            if self._mic_dead:
                log.warning(f"[MicManager] Mic is dead — acquisition by '{owner_name}' denied.")
                return None

            thread_name = threading.current_thread().name

            if self._owner is None:
                self._owner = MicOwner(mode=mode, owner_name=owner_name,
                                       acquired_at=time.time(), thread_name=thread_name)
                log.info(f"[MicManager] ACQUIRED by {owner_name} ({mode.name})")
                return MicToken(_manager=self, _mode=mode, _owner=owner_name)

            if self._owner.owner_name == owner_name:
                if self._owner.mode >= mode:
                    log.debug(f"[MicManager] Re-acquiring same mode: {owner_name} ({mode.name})")
                    return MicToken(_manager=self, _mode=mode, _owner=owner_name)
                log.warning(f"[MicManager] Downgrade rejected: {owner_name} ({mode.name}) "
                            f"but held as {self._owner.mode.name}")
                return None

            if mode > self._owner.mode:
                old_owner = self._owner.owner_name
                log.warning(f"[MicManager] PREEMPT: {owner_name} ({mode.name}) "
                            f"pre-empts {old_owner} ({self._owner.mode.name})")
                self._release_current_locked()
                self._owner = MicOwner(mode=mode, owner_name=owner_name,
                                       acquired_at=time.time(), thread_name=thread_name)
                log.info(f"[MicManager] ACQUIRED (preempted) by {owner_name} ({mode.name})")
                return MicToken(_manager=self, _mode=mode, _owner=owner_name)

            log.debug(f"[MicManager] Contention: {owner_name} ({mode.name}) "
                      f"blocked by {self._owner.owner_name} ({self._owner.mode.name})")
            self._queue_contention(mode, owner_name)
            return None

    def _release_current_locked(self):
        """Release current owner (must hold self._lock)."""
        if self._owner is None:
            return
        prev = self._owner
        self._owner = None
        log.info(f"[MicManager] RELEASED by {prev.owner_name} ({prev.mode.name}) "
                 f"— held for {time.time() - prev.acquired_at:.1f}s")
        self._notify_available()
        self._dispatch_contention()

    def release(self, owner_name: str):
        """Release the microphone. Must be called by the current owner."""
        with self._lock:
            if self._owner is None:
                return
            if self._owner.owner_name != owner_name:
                log.warning(f"[MicManager] Release denied: '{owner_name}' "
                            f"does not own the mic (owner: '{self._owner.owner_name}')")
                return
            self._release_current_locked()

    def force_release(self, reason: str = "force"):
        """Force release for recovery / shutdown."""
        with self._lock:
            if self._owner:
                log.warning(f"[MicManager] Force release: {reason} — "
                            f"'{self._owner.owner_name}' disconnected")
                self._owner = None
                self._notify_available()
                self._dispatch_contention()

    def mark_dead(self, reason: str = ""):
        """Mark the microphone as unavailable (hardware error, OS lock)."""
        with self._lock:
            self._mic_dead = True
            self._owner = None
            print(f"[MicManager] Microphone marked DEAD: {reason}")

    def mark_alive(self):
        """Re-enable microphone acquisition (after device reconnection)."""
        with self._lock:
            if self._mic_dead:
                self._mic_dead = False
                self._recovery_count = 0
                print("[MicManager] Microphone marked ALIVE — reconnection detected.")

    def on_available(self, callback: Callable[[], None]):
        """Register a callback to fire when the mic becomes available."""
        with self._contention_lock:
            self._available_callbacks.append(callback)

    def _notify_available(self):
        for cb in self._available_callbacks:
            try:
                cb()
            except Exception as e:
                log.debug(f"[MicManager] Available callback error: {e}")

    def _queue_contention(self, mode: MicMode, owner_name: str):
        with self._contention_lock:
            self._contention_queue.append((mode, owner_name))

    def _dispatch_contention(self):
        """Wake up the highest-priority waiting owner."""
        with self._contention_lock:
            if not self._contention_queue:
                return
            self._contention_queue.sort(key=lambda x: x[0], reverse=True)
            mode, owner_name = self._contention_queue.pop(0)
            log.info(f"[MicManager] Dispatching contention: {owner_name} ({mode.name})")
            if self._contention_sem.acquire(blocking=False):
                threading.Thread(
                    target=self._notify_waiter,
                    args=(mode, owner_name),
                    daemon=True,
                    name="MicContentionNotify",
                ).start()
            else:
                # Too many in-flight — re-queue
                self._contention_queue.append((mode, owner_name))
                log.debug(f"[MicManager] Contention notify throttled for {owner_name}")

    def _notify_waiter(self, mode: MicMode, owner_name: str):
        """Attempt to acquire again after previous owner released."""
        try:
            time.sleep(0.1)
            token = self.acquire(mode, owner_name)
            if not token:
                # Re-queue so the subsystem gets another chance
                log.debug(f"[MicManager] Contention re-queue for {owner_name}")
                self._queue_contention(mode, owner_name)
        finally:
            self._contention_sem.release()

    def schedule_recovery(self, retry_after_sec: float = 5.0):
        """Schedule a mic recovery attempt (after OS releases the device)."""
        if self._recovery_thread and self._recovery_thread.is_alive():
            return
        self._recovery_deadline = time.time() + retry_after_sec
        self._recovery_count += 1
        self._recovery_thread = threading.Thread(
            target=self._do_recovery,
            args=(retry_after_sec,),
            daemon=True,
            name="MicRecovery",
        )
        self._recovery_thread.start()

    def _do_recovery(self, delay: float):
        time.sleep(delay)
        self.mark_alive()
        log.info(f"[MicManager] Recovery attempt #{self._recovery_count} complete.")

    @property
    def current_owner(self) -> Optional[MicOwner]:
        with self._lock:
            return self._owner

    @property
    def mode(self) -> MicMode:
        with self._lock:
            return self._owner.mode if self._owner else MicMode.IDLE

    @property
    def is_available(self) -> bool:
        return self.current_owner is None and not self._mic_dead

    def status(self) -> str:
        owner = self.current_owner
        if self._mic_dead:
            return f"MIC DEAD — recovery #{self._recovery_count}"
        if owner is None:
            return "MIC AVAILABLE"
        return (f"MIC HELD by {owner.owner_name} ({owner.mode.name}) — "
                f"{time.time() - owner.acquired_at:.1f}s")

    def diagnostics(self) -> dict:
        with self._lock:
            owner = self.current_owner
            return {
                "owner": owner.owner_name if owner else None,
                "mode": owner.mode.name if owner else MicMode.IDLE.name,
                "held_sec": time.time() - owner.acquired_at if owner else 0.0,
                "dead": self._mic_dead,
                "recovery_count": self._recovery_count,
                "contention_queue": len(self._contention_queue),
            }


class MicToken:
    """RAII-style token. Release on __exit__ or when done."""

    def __init__(self, _manager: MicrophoneManager, _mode: MicMode, _owner: str):
        self._manager = _manager
        self._mode = _mode
        self._owner = _owner
        self._released = False

    def release(self):
        if not self._released:
            self._released = True
            self._manager.release(self._owner)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


_instance: Optional[MicrophoneManager] = None
_manager_lock = threading.Lock()


def get_microphone_manager() -> MicrophoneManager:
    global _instance
    with _manager_lock:
        if _instance is None:
            _instance = MicrophoneManager()
        return _instance
