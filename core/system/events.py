from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class Event:
    """Base class for all JARVIS events."""
    timestamp: float = field(default_factory=lambda: __import__("time").time())

@dataclass
class EventSpeechRequested(Event):
    text: str = ""
    voice_mode: str = "idle"
    priority: str = "default"

@dataclass
class EventSystemAlert(Event):
    level: str = "info"  # info, warning, critical, danger
    title: str = ""
    message: str = ""
    source: str = "system"

@dataclass
class EventEngineLoaded(Event):
    engine_name: str = ""
    success: bool = True
    error: Optional[str] = None

@dataclass
class EventCommandReceived(Event):
    text: str = ""
    source: str = "voice"  # voice, web, terminal

@dataclass
class EventStatusUpdate(Event):
    status: str = ""
    source: str = "brain"

@dataclass
class EventNtfyPush(Event):
    title: str = ""
    message: str = ""
    priority: str = "default"
    tags: str = "robot"

@dataclass
class EventApprovalRequest(Event):
    """Published by ApprovalService when a high-risk shell command needs user consent."""
    request_id: str = ""
    command:    str = ""
    context:    str = ""
    timeout_s:  float = 30.0
