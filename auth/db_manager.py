import sqlite3
import hashlib
import os
import time
import threading

# Prefer bcrypt for salted password hashing; fall back to SHA-256 with a
# per-installation salt derived from the DB path (still far stronger than plain SHA-256).
try:
    import bcrypt as _bcrypt
    _BCRYPT_OK = True
except ImportError:
    _BCRYPT_OK = False

DB_PATH = "jarvis_auth.db"
SESSION_DURATION = 480   # 8 minutes — balance between convenience and security


def _hash_pin(pin: str) -> str:
    """Hash a PIN using bcrypt (preferred) or per-PIN salted SHA-256 (fallback)."""
    if _BCRYPT_OK:
        hashed = _bcrypt.hashpw(pin.encode(), _bcrypt.gensalt())
        return hashed.decode("utf-8")
    # Fallback: generate a cryptographically random 32-byte salt per PIN.
    # Stored format: 'sha256:<salt_hex>:<hash_hex>'
    salt = os.urandom(32)
    digest = hashlib.sha256(salt + pin.encode()).hexdigest()
    return f"sha256:{salt.hex()}:{digest}"


def _verify_pin_hash(pin: str, stored: str) -> bool:
    """Verify a PIN against a stored hash (bcrypt or salted SHA-256)."""
    if _BCRYPT_OK and stored.startswith("$2b$"):
        try:
            return _bcrypt.checkpw(pin.encode(), stored.encode())
        except Exception:
            return False
    # Fallback: extract the per-PIN salt from the stored record
    if stored.startswith("sha256:"):
        try:
            _, salt_hex, stored_digest = stored.split(":")
            salt = bytes.fromhex(salt_hex)
            return hashlib.sha256(salt + pin.encode()).hexdigest() == stored_digest
        except Exception:
            return False
    # Legacy: plain SHA-256 without salt — always fail to force re-registration
    return False


class DBManager:
    def __init__(self):
        print("[AuthDB] Connecting to auth db...")
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._lock = threading.Lock()   # serialises all DB operations
        print("[AuthDB] Initializing tables...")
        self.init_tables()
        print("[AuthDB] Init complete.")

    def init_tables(self):
        with self._lock:
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                pin_hash TEXT,
                failed_attempts INTEGER DEFAULT 0,
                lockout_until INTEGER DEFAULT 0
            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                trusted INTEGER
            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT,
                expiry INTEGER
            )
            """)

            self.conn.commit()

    def store_pin(self, pin):
        pin_hash = _hash_pin(pin)
        with self._lock:
            self.cursor.execute("DELETE FROM users")
            self.cursor.execute(
                "INSERT INTO users (pin_hash, failed_attempts, lockout_until) VALUES (?, 0, 0)",
                (pin_hash,)
            )
            self.conn.commit()

    def has_pin(self) -> bool:
        with self._lock:
            self.cursor.execute("SELECT 1 FROM users LIMIT 1")
            return self.cursor.fetchone() is not None

    def get_lockout_remaining(self):
        with self._lock:
            self.cursor.execute("SELECT lockout_until FROM users LIMIT 1")
            row = self.cursor.fetchone()
        if not row: return 0
        remaining = row[0] - int(time.time())
        return max(0, remaining)

    def verify_pin(self, pin):
        # 1. Check lockout
        remaining = self.get_lockout_remaining()
        if remaining > 0:
            return False, f"Locked out. Try again in {remaining} seconds."

        with self._lock:
            self.cursor.execute("SELECT pin_hash, failed_attempts FROM users LIMIT 1")
            row = self.cursor.fetchone()

        if not row:
            return False, "No PIN set."

        pin_hash, failed = row

        # 2. Verify
        if _verify_pin_hash(pin, pin_hash):
            with self._lock:
                self.cursor.execute("UPDATE users SET failed_attempts = 0, lockout_until = 0")
                self.conn.commit()
            return True, "Success"

        # 3. Failure: increment and check for lockout
        new_failed = failed + 1
        lockout_time = 0
        if new_failed >= 5:
            # 5 fails=1 min, 6 fails=5 mins, 7+ fails=15 mins
            if new_failed == 5:   lockout_time = 60
            elif new_failed == 6: lockout_time = 300
            else:                 lockout_time = 900

            until = int(time.time()) + lockout_time
            with self._lock:
                self.cursor.execute(
                    "UPDATE users SET failed_attempts = ?, lockout_until = ?",
                    (new_failed, until)
                )
                self.conn.commit()
            return False, f"Too many failed attempts. Locked out for {lockout_time}s."

        with self._lock:
            self.cursor.execute("UPDATE users SET failed_attempts = ?", (new_failed,))
            self.conn.commit()

        return False, f"Incorrect PIN. {5 - new_failed} attempts remaining."

    def is_device_trusted(self, device_id):
        with self._lock:
            self.cursor.execute(
                "SELECT trusted FROM devices WHERE device_id=?",
                (device_id,)
            )
            row = self.cursor.fetchone()
        return row and row[0] == 1

    def trust_device(self, device_id):
        with self._lock:
            self.cursor.execute(
                "INSERT OR REPLACE INTO devices VALUES (?, 1)",
                (device_id,)
            )
            self.conn.commit()

    def create_session(self, token, duration=SESSION_DURATION):
        expiry = int(time.time()) + duration
        with self._lock:
            self.cursor.execute("DELETE FROM sessions")
            self.cursor.execute(
                "INSERT INTO sessions VALUES (?, ?)",
                (token, expiry)
            )
            self.conn.commit()

    def is_session_valid(self):
        with self._lock:
            self.cursor.execute("SELECT expiry FROM sessions LIMIT 1")
            row = self.cursor.fetchone()
        if not row:
            return False
        return int(time.time()) < row[0]

    def get_session_remaining(self) -> int:
        """Returns seconds remaining in the current session, or 0 if none/expired."""
        with self._lock:
            self.cursor.execute("SELECT expiry FROM sessions LIMIT 1")
            row = self.cursor.fetchone()
        if not row:
            return 0
        return max(0, row[0] - int(time.time()))
