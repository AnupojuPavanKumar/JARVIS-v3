import logging
import os
import datetime
import json

LOG_PATH = "logs/security.log"

class SecurityLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SecurityLogger, cls).__new__(cls)
            cls._instance._init_logger()
        return cls._instance

    def _init_logger(self):
        os.makedirs("logs", exist_ok=True)
        self.logger = logging.getLogger("Security")
        self.logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def log_event(self, event_type: str, status: str, details: str = "", device_id: str = ""):
        entry = {
            "event": event_type,
            "status": status,
            "details": details,
            "device": device_id
        }
        self.logger.info(json.dumps(entry))

def get_security_logger():
    return SecurityLogger()
