import logging
import os
from pathlib import Path

def setup_jarvis_logging(level=logging.INFO):
    """
    Configures structured logging for the JARVIS system.
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
        logging.FileHandler(log_dir / "jarvis.log"),
        logging.StreamHandler()
        ]
    )

    # Set specific levels for noisy libraries
    logging.getLogger("PyQt6").setLevel(logging.WARNING)
    logging.getLogger("OpenGL").setLevel(logging.WARNING)

def get_logger(name):
    return logging.getLogger(name)
