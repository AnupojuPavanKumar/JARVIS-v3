# core/executor/media_executor.py — Media Executor Plugin
"""Handles MEDIA_CONTROL using Win32 virtual key codes."""

import ctypes
import logging

log = logging.getLogger("MediaExecutor")

VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK  = 0xB0
VK_MEDIA_PREV_TRACK  = 0xB1
VK_MEDIA_STOP        = 0xB2
KEYEVENTF_KEYUP      = 0x0002


class MediaExecutor:
    """Send media key events to the active media session."""

    def control(self, action: str) -> tuple[bool, str]:
        try:
            user32 = ctypes.windll.user32
            vk = {
                "play":    VK_MEDIA_PLAY_PAUSE,
                "pause":   VK_MEDIA_PLAY_PAUSE,
                "resume":  VK_MEDIA_PLAY_PAUSE,
                "next":    VK_MEDIA_NEXT_TRACK,
                "previous":VK_MEDIA_PREV_TRACK,
                "prev":    VK_MEDIA_PREV_TRACK,
                "stop":    VK_MEDIA_STOP,
            }.get(action)

            if vk is None:
                return False, f"Unknown media action: '{action}'"

            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            labels = {"play": "Playing", "pause": "Paused", "resume": "Playing",
                      "next": "Skipping", "previous": "Going back", "prev": "Going back", "stop": "Stopped"}
            return True, f"{labels.get(action, action.title())}, sir."
        except Exception as e:
            log.warning(f"[MediaExecutor] Error: {e}")
            return False, "Media control unavailable."