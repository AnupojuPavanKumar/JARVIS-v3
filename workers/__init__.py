# workers/__init__.py — JARVIS Worker Package
"""
JARVIS autonomous worker processes.

workers.vision_worker       — VisionWorker: captures frames, publishes VisionMetadata
workers.voice_output_worker — VoiceOutputWorker: Stream-to-Audio TTS from response.text
"""
from workers.vision_worker import get_vision_worker
from workers.voice_output_worker import get_voice_output_worker

__all__ = ["get_vision_worker", "get_voice_output_worker"]
