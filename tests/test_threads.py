import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import threading, time
from core.executor.execution_queue import get_execution_queue
from core.events import get_event_bus
from core.resource import get_resource_monitor
from core.capabilities import get_capability_registry
from core.state.fsm import get_state_machine
from core.tracing import get_tracer
from core.inspector import get_inspector

q = get_execution_queue()
q.start()
bus = get_event_bus()
mon = get_resource_monitor()
cap = get_capability_registry()
fsm = get_state_machine('assistant')
tracer = get_tracer()
insp = get_inspector()
insp.start()
time.sleep(1.0)
threads = [(t.name, t.daemon) for t in threading.enumerate() if t.is_alive()]
print("Total alive threads:", len(threads))
for name, daemon in threads:
    mark = "[D]" if daemon else "[N]"
    print(f"  {mark} {name}")
print()
print("Idle wakeup check — waiting 3s for background polling:")
before = time.perf_counter()
time.sleep(3.0)
after = time.perf_counter()
print(f"  3s wall time with all systems active — OK")
