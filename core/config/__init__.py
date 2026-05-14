# core/config/__init__.py
"""
Hot reloadable configuration — P13.
Live policy reload, executor config reload, routing threshold updates.
Config validation, rollback on invalid configs, live diagnostics.
"""
from core.config.manager import ConfigManager, ConfigSchema, get_config_manager

__all__ = ["ConfigManager", "ConfigSchema", "get_config_manager"]
