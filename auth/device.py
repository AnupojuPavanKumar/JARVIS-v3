import uuid
import platform
import hashlib


def get_device_id():
    raw = f"{uuid.getnode()}-{platform.system()}-{platform.processor()}"
    return hashlib.sha256(raw.encode()).hexdigest()