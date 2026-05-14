# core/platform/__init__.py
"""
Platform abstraction layer.
Provides a unified interface for platform-specific operations,
with clean boundaries between windows/linux/mac.
"""
from core.platform.base import PlatformCapabilities, PlatformAdapter

def get_platform() -> PlatformAdapter:
    """Return the current platform adapter."""
    import sys
    if sys.platform == "win32":
        from core.platform.windows import WindowsAdapter
        return WindowsAdapter()
    elif sys.platform == "darwin":
        from core.platform.mac import MacAdapter
        return MacAdapter()
    else:
        from core.platform.linux import LinuxAdapter
        return LinuxAdapter()
