import threading
import time
from typing import Callable, Optional
from core.system.event_bus import get_event_bus
from core.system.events import EventEngineLoaded

from core.system.service_registry import get_service_registry

class Bootstrapper:
    """
    Handles asynchronous initialization of heavy JARVIS engines.
    Publishes EventEngineLoaded for each module and registers them
    with the central ServiceRegistry.
    """
    def __init__(self, brain):
        self.brain = brain
        self.bus = get_event_bus()
        self.registry = get_service_registry()

    def start(self):
        # Run boot sequence
        self._run_boot_sequence()
        
        # Async maintenance to preserve Recovery Integrity
        def run_maintenance():
            try:
                from core.system.db import get_db
                get_db().vacuum(prune_telemetry_days=7)
            except Exception as e:
                print(f"[Bootstrapper] Maintenance failed: {e}")
                
        threading.Thread(target=run_maintenance, daemon=True).start()

    def _run_boot_sequence(self):
        start_time = time.time()
        
        engines = [
            ("skill_factory",    'core.api.skill_factory',    "get_skill_factory"),
            ("task_queue",       'core.agent.task_queue',       "get_task_queue")
        ]

        from concurrent.futures import ThreadPoolExecutor
        
        # We use a small pool to avoid overwhelming the system, but parallelize I/O heavy imports
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="BootLoader") as executor:
            futures = {executor.submit(self._load_engine, e): e for e in engines}
            from concurrent.futures import as_completed
            for future in as_completed(futures):
                pass # Results are handled inside _load_engine

        self.brain._bg_ready = True
        print(f"[Bootstrapper] All engines ready in {time.time() - start_time:.2f}s")

    def _load_engine(self, engine_def):
        attr_name, module_path, factory_name = engine_def
        print(f"[Bootstrapper] Loading: {attr_name}...")
        try:
            # Dynamic import to keep bootstrap light
            module = __import__(module_path, fromlist=[factory_name])
            factory = getattr(module, factory_name)
            engine_instance = factory()
            
            # Register with ServiceRegistry
            self.registry.register(attr_name, engine_instance)
            
            # Update brain reference (maintaining backward compatibility)
            # Use a lock if brain is not thread-safe for attribute setting
            setattr(self.brain, f"_{attr_name}", engine_instance)
            
            # Special wiring for specific engines
            self._post_init_wiring(attr_name, engine_instance)
            
            # Mark as ready in registry
            self.registry.mark_ready(attr_name)
            
            self.bus.publish(EventEngineLoaded(engine_name=attr_name, success=True))
            print(f"[Bootstrapper] Ready: {attr_name}")
        except Exception as e:
            print(f"[Bootstrapper] FAILED: {attr_name} — {e}")
            self.bus.publish(EventEngineLoaded(engine_name=attr_name, success=False, error=str(e)))


    def _post_init_wiring(self, name: str, instance: any):
        """Handle inter-engine dependencies during boot."""
        if name == "sys_watcher":
            instance.set_alert_callback(self.brain._handle_system_alert)
            instance.watch_process("ollama.exe", auto_restart=True, restart_cmd="ollama serve")
            instance.start()
        elif name == "task_queue":
            instance._agent_fn = self.brain._run_agent_task
        elif name == "learning":
            instance.start_nightly_reflection()
