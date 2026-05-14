from .db_manager import DBManager
from .device import get_device_id
from .session import generate_session_token
from core.system.security_logger import get_security_logger


class AuthManager:
    def __init__(self):
        print("[Auth] Initializing DBManager...")
        self.db = DBManager()
        print("[Auth] Getting device ID...")
        self.device_id = get_device_id()
        self.failed_attempts = 0
        self.logger = get_security_logger()
        print("[Auth] Init complete.")

    def should_authenticate(self):
        return not self.db.is_session_valid()

    def is_known_device(self):
        return self.db.is_device_trusted(self.device_id)

    def handle_successful_auth(self, method="unknown"):
        token = generate_session_token()
        self.db.create_session(token)

        if not self.is_known_device():
            self.db.trust_device(self.device_id)
            self.logger.log_event("trust_device", "success", "New device trusted", self.device_id)

        self.failed_attempts = 0
        self.logger.log_event("auth", "success", f"Method: {method}", self.device_id)

    def handle_failed_face(self):
        self.failed_attempts += 1
        self.logger.log_event("auth_face", "fail", f"Attempt: {self.failed_attempts}", self.device_id)

    def require_pin(self):
        return self.failed_attempts >= 3 or not self.is_known_device()

    def verify_pin(self, pin):
        success, message = self.db.verify_pin(pin)
        if success:
            self.handle_successful_auth(method="pin")
            return True, message

        self.logger.log_event("auth_pin", "fail", message, self.device_id)
        return False, message

    def get_lockout_remaining(self):
        return self.db.get_lockout_remaining()

    def get_session_remaining(self) -> int:
        """Seconds left in the active session (0 if none or expired)."""
        return self.db.get_session_remaining()