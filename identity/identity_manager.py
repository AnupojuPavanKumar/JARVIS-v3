import json
import os

from identity.face_auth import FaceAuth


from core.system.db import get_db

class IdentityManager:

    def __init__(self):
        print("[ID] Connecting to SystemDB...", flush=True)
        self.db = get_db()
        print("[ID] Initializing FaceAuth...", flush=True)
        self.auth = FaceAuth()
        self.secure_auth = None
        self.identity = "guest"
        self.user_name = "Guest"
        print("[ID] Ensuring AuthManager...", flush=True)
        self._ensure_auth_manager()
        print("[ID] Migrating legacy profile...", flush=True)
        self._migrate_legacy_profile()
        print("[ID] Loading profile...", flush=True)
        self.load_profile()
        print("[ID] IdentityManager init complete.", flush=True)

    def _migrate_legacy_profile(self):
        """Move data from profile.json to SystemDB if it exists."""
        legacy_path = "memory/profile.json"
        if os.path.exists(legacy_path):
            try:
                with open(legacy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    name = data.get("owner_name")
                    if name:
                        self.db.set_setting("owner_name", name)
                # Rename instead of delete to be safe during migration
                os.rename(legacy_path, legacy_path + ".migrated")
            except Exception:
                pass

    def _ensure_auth_manager(self):
        if self.secure_auth is None:
            from auth.auth_manager import AuthManager
            self.secure_auth = AuthManager()

    def load_profile(self):
        self.user_name = self.db.get_setting("owner_name", "Guest")

    def has_profile(self) -> bool:
        self._ensure_auth_manager()
        return self.db.get_setting("owner_name") is not None and self.secure_auth.db.has_pin()

    def requires_initial_setup(self) -> bool:
        return not self.has_profile()

    def setup_owner(self, owner_name: str, pin: str) -> str:
        self._ensure_auth_manager()
        owner_name = owner_name.strip()
        pin = pin.strip()
        if len(owner_name) < 2:
            raise ValueError("Owner name must be at least 2 characters.")
        if len(pin) < 4:
            raise ValueError("PIN must be at least 4 digits.")

        self.db.set_setting("owner_name", owner_name)

        self.secure_auth.db.store_pin(pin)
        self.secure_auth.handle_successful_auth()
        self.identity = "owner"
        self.user_name = owner_name
        return "owner"

    def mark_authenticated(self) -> str:
        self._ensure_auth_manager()
        self.secure_auth.handle_successful_auth()
        self.identity = "owner"
        self.load_profile()
        return "owner"

    def verify_pin(self, pin: str) -> tuple[bool, str]:
        self._ensure_auth_manager()
        success, message = self.secure_auth.verify_pin(pin.strip())
        if not success:
            return False, message
        self.mark_authenticated()
        return True, "Success"

    def initialize(self):
        """
        Determines the auth path on startup.
        Returns:
          'owner'          — trusted device + valid session (auto-unlock)
          'guest'          — needs face/PIN auth via AuthWindow
          'setup_required' — first run, no profile exists
        """
        self._ensure_auth_manager()

        # Must complete setup first — no bypass possible
        if self.requires_initial_setup():
            return "setup_required"

        # Only auto-unlock if BOTH conditions hold:
        #   1. The device is explicitly trusted (was enrolled on this machine)
        #   2. A valid (unexpired) session token exists
        # This prevents session token reuse on unknown devices
        device_trusted = self.secure_auth.is_known_device()
        session_valid  = not self.secure_auth.should_authenticate()

        if device_trusted and session_valid:
            remaining = self.secure_auth.get_session_remaining()
            print(f"[AUTH] Trusted device + valid session — auto-unlocking. ({remaining}s remaining)")
            return self.mark_authenticated()

        # All other cases: force full auth through AuthWindow
        self.identity = "guest"
        self.load_profile()
        return "guest"

    def get_greeting(self):
        if self.identity == "owner":
            return (
                f"Agentic core online. Neural pathways linked. "
                f"Welcome back, {self.user_name}. What are we building today?"
            )
        return "Unauthorized access attempt logged. Who are you?"

    def get_session_remaining(self) -> int:
        """Returns seconds remaining in the current active session, or 0."""
        self._ensure_auth_manager()
        return self.secure_auth.get_session_remaining()
