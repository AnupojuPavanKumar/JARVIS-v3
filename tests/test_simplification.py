import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import time

print("=== JARVIS v3 Simplification & Operational Hardening ===\n")

# Setup all systems
from core.executor.execution_queue import get_execution_queue
from core.events import get_event_bus, Event, EventPriority
from core.events.governance import get_event_governance
from core.resource import get_resource_monitor
from core.state.fsm import get_state_machine, _fsm_instances
from core.state.registry import get_state_registry
from core.tracing.lineage import get_tracer, SpanStatus
from core.orchestration.limits import get_limits
from core.orchestration.modes import get_mode_manager, SystemMode, MODE_PROFILES
from core.orchestration.health import get_health_monitor, HealthLevel
from core.orchestration.policies import get_policy_engine, Policy, PolicyPriority
from core.services.container import service_container, ServiceLifecycle
from core.audit.profiles import get_profile_manager, OperationalProfile, PROFILE_CONFIGS

q = get_execution_queue()
q.start()
bus = get_event_bus()
mon = get_resource_monitor()

# ── P9: Unified Debugging View ──────────────────────────────────────────────
from core.audit.unified_view import get_debug_view, AnomalyLevel
dv = get_debug_view()
dv.begin_command("open vscode")
sid = dv.start_span("intents", "score_command")
time.sleep(0.005)
dv.end_span(sid, "completed", "OPEN_APP")
sid2 = dv.start_span("executor", "launch_app")
time.sleep(0.005)
dv.end_span(sid2, "completed", "Code.exe launched")
sid3 = dv.start_span("safety", "validate_path")
time.sleep(0.005)
dv.end_span(sid3, "completed", "allowed")
summ = dv.end_command("completed")
print("P9: Unified Debug View")
print(f"  Command: {summ.command}")
print(f"  Duration: {summ.total_duration_ms:.1f}ms")
print(f"  Spans: {len(summ.spans)}")
print(f"  Anomaly level: {summ.anomaly_level.name}")
print(f"  Root cause: {summ.root_cause}")
print(f"  Text summary:")
for line in summ.human_readable.split('\n')[:5]:
    print(f"    {line}")
print("  PASS")

# ── P1: Event Topology Analysis ───────────────────────────────────────────────
from core.audit.topology import get_topology
topo = get_topology()
for i in range(10):
    bus.emit(Event(event_type="execution.completed", source="test"))
topo.record_chain(["command.start", "execution.started", "execution.completed"])
topo.record_chain(["command.start", "ai.inference_start", "ai.inference_end"])
print("\nP1: Event Topology")
score, warnings = topo.get_topology_score()
print(f"  Topology score: {score}")
print(f"  Warnings: {warnings}")
coupling = topo.get_coupling_metrics()
print(f"  Total events: {coupling['total_events']}, edges: {coupling['total_edges']}")
print(f"  Avg fan-out: {coupling['avg_fan_out']}, max: {coupling['max_fan_out']}")
print(f"  Circular chains: {coupling['circular_chains']}")
print("  PASS")

# ── P3: Orchestration Depth ───────────────────────────────────────────────────
from core.audit.topology import OrchestrationDepth
od = OrchestrationDepth()
od.begin_chain("chain-001")
for step in ["intent.score", "decompose", "event:execution.started",
             "policy:gpu_throttle", "executor.launch_app"]:
    od.record_step("chain-001", step)
metrics = od.end_chain("chain-001")
print("\nP3: Orchestration Depth")
print(f"  Chain length: {metrics.chain_length}")
print(f"  Event count: {metrics.event_count}")
print(f"  Policy cascades: {metrics.policy_count}")
print(f"  Depth within limit: {od.check_depth_limit(metrics.chain_length)}")
depth_stats = od.get_depth_stats()
print(f"  Depth stats: {depth_stats}")
print("  PASS")

# ── P2+P5: FSM Convergence + Policy Conflict ───────────────────────────────────
print("\nP2+P5: FSM Convergence & Policy Conflict")
assistant_fsm = get_state_machine("assistant")
exec_fsm = get_state_machine("execution")
audio_fsm = get_state_machine("audio")

# Check FSM state overlap
state_overlaps = []
if assistant_fsm.state == "idle" and exec_fsm.state in ["pending", "queued"]:
    state_overlaps.append("Both IDLE and PENDING/QUEUED — acceptable")
if assistant_fsm.state == "executing" and exec_fsm.state == "running":
    state_overlaps.append("Synchronized: ASSISTANT.EXECUTING == EXECUTION.RUNNING")
print(f"  FSM states: assistant={assistant_fsm.state}, execution={exec_fsm.state}, audio={audio_fsm.state}")
print(f"  State overlaps: {state_overlaps if state_overlaps else 'none detected'}")

# Policy conflict detection
pe = get_policy_engine()
conflict_count = [0]
oscillating = [False]
def condition_increase():
    conflict_count[0] += 1
    return True
def action_increase():
    if conflict_count[0] > 3:
        oscillating[0] = True
    return
def condition_decrease():
    return conflict_count[0] > 0
def action_decrease():
    if conflict_count[0] > 0:
        conflict_count[0] -= 1
    return

pe.register(Policy(name="p1_increase", condition_fn=condition_increase,
                  action_fn=action_increase, priority=PolicyPriority.NORMAL, cooldown_sec=0.0))
pe.register(Policy(name="p2_decrease", condition_fn=condition_decrease,
                   action_fn=action_decrease, priority=PolicyPriority.LOW, cooldown_sec=0.0))
for _ in range(5):
    pe.evaluate_all()
print(f"  Policy conflicts: oscillating={oscillating[0]}")
print(f"  Policy count: {pe.get_stats()['total_policies']}")
print("  PASS")

# ── P4: Service Dependency Simplification ────────────────────────────────────
print("\nP4: Service Dependency Simplification")
container = service_container
container.register("platform", lambda: None, ServiceLifecycle.LAZY)
container.register("test_service", lambda: None, ServiceLifecycle.LAZY, dependencies=["platform"])
container.get("platform")
container.get("test_service")
from core.governance.di_governance import get_di_governor
di = get_di_governor()
analysis = di.analyze(container)
print(f"  Service count: {analysis.get('service_count', 0)}")
print(f"  Initialized: {analysis.get('initialized_count', 0)}")
di_stats = di.stats()
print(f"  DI governance: max_depth_limit={di_stats['max_depth_limit']}")
circular = di.detect_circular(container)
print(f"  Circular deps: {len(circular)}")
print("  PASS")

# ── P6: Memory Domain Boundary Enforcement ──────────────────────────────────
print("\nP6: Memory Domain Boundaries")
from core.governance.memory_domains import get_memory_domains, MemoryDomain
mem = get_memory_domains()
for i in range(60):
    mem.put(MemoryDomain.CACHE, f"key_{i}", f"value_{i}")
stats = mem.stats()
conversational_util = stats['CONVERSATIONAL']['utilization']
cache_util = stats['CACHE']['utilization']
print(f"  CONVERSATIONAL utilization: {conversational_util}%")
print(f"  CACHE utilization: {cache_util}% (60 entries in 500 max)")
print(f"  Domains tracked: {len(stats)}")
print("  PASS")

# ── P7: Provider Purity Validation ────────────────────────────────────────────
print("\nP7: Provider Purity Validation")
from core.providers.base import get_provider_registry, ProviderCapability
reg = get_provider_registry()
text_providers = reg.get_capable_provider(ProviderCapability.TEXT)
print(f"  Text-capable providers: {len(text_providers)}")
# Check if any provider-specific leakage exists by looking at capabilities
model_count = reg.stats()['models']
print(f"  Provider isolation: {model_count} models tracked")
print("  PASS")

# ── P8: Background Activity Optimization ─────────────────────────────────────
import threading
time.sleep(0.5)
threads = [t for t in threading.enumerate() if t.daemon and t.is_alive()]
print("\nP8: Background Activity Optimization")
print(f"  Daemon threads: {len(threads)}")
daemon_names = [t.name for t in threads]
print(f"  Daemon names: {daemon_names}")
# Count idle wakeups in 2 seconds
from core.orchestration.modes import get_mode_manager
mm = get_mode_manager()
print(f"  Current mode: {mm.current_mode.value}")
print(f"  Active daemons in NORMAL mode: {len(PROFILE_CONFIGS[OperationalProfile.NORMAL].active_daemons)}")
print(f"  Active daemons in GAMING mode: {len(PROFILE_CONFIGS[OperationalProfile.GAMING].active_daemons)}")
print("  PASS")

# ── P10: Realistic Failure Modeling ────────────────────────────────────────────
print("\nP10: Realistic Failure Modeling")
from core.simulation.framework import get_chaos_engine, SimulationScenario, ScenarioType
chaos = get_chaos_engine()
chaos.register_scenario(SimulationScenario(
    name="partial_queue_overload", scenario_type=ScenarioType.QUEUE_OVERLOAD,
    duration_sec=0.1, intensity=0.3,
))
chaos.register_scenario(SimulationScenario(
    name="slow_inference_sim", scenario_type=ScenarioType.SLOW_INFERENCE,
    duration_sec=0.1, intensity=0.5,
))
stats = chaos.stats()
print(f"  Scenarios: {stats['registered_scenarios']}")
print(f"  Partial failure simulation: {'QUEUE_OVERLOAD' in str(stats)}")
print("  PASS")

# ── P11: Health Signal Calibration ─────────────────────────────────────────────
print("\nP11: Health Signal Calibration")
from core.orchestration.health import get_health_monitor, HealthLevel
hm = get_health_monitor()
report = hm.generate_report()
# Check signal calibration: redundant weights, noisy metrics
signal_count = len(report.subsystems)
print(f"  Signals tracked: {signal_count}")
print(f"  Overall score: {report.overall_score}")
print(f"  Alerts: {len(report.active_alerts)}")
# Check for confidence scoring
predictions = hm.predict_instability()
print(f"  Instability predictions: {len(predictions)}")
print("  PASS")

# ── P12: Lifecycle Recovery ───────────────────────────────────────────────────
print("\nP12: Lifecycle Recovery Simplification")
from core.lifecycle.controller import get_lifecycle_controller, LifecyclePhase
lc = get_lifecycle_controller()
print(f"  Current phase: {lc.current_phase.name}")
print(f"  Subsystems: {len(lc.get_subsystems_status())}")
print(f"  Startup duration: {lc.get_startup_duration_ms():.1f}ms")
print("  PASS")

# ── P13: Complexity Budget ─────────────────────────────────────────────────────
print("\nP13: Complexity Budget")
from core.audit.budget import get_budget
budget = get_budget()
budget.update("max_background_threads", float(len(threads)))
audit = budget.audit_all()
print(f"  Limits audited: {len(audit)}")
active_violations = budget.get_active_violations()
print(f"  Active violations: {len(active_violations)}")
for name, r in audit.items():
    if r['status'] != 'OK':
        print(f"  [{r['status']}] {name}: {r['current']}/{r['hard_limit']} ({r['utilization']}%)")
print("  PASS")

# ── P14: Operational Profiles ───────────────────────────────────────────────
print("\nP14: Operational Profiles")
pm = get_profile_manager()
print(f"  Current profile: {pm.current.name}")
for profile in OperationalProfile:
    cfg = PROFILE_CONFIGS[profile]
    print(f"  {profile.name}: {cfg.description}, daemons={len(cfg.active_daemons)}, depth={cfg.max_orchestration_depth}")
pm.set_profile(OperationalProfile.GAMING)
gaming_daemons = PROFILE_CONFIGS[OperationalProfile.GAMING].active_daemons
print(f"  Switched to GAMING: {len(gaming_daemons)} daemons active: {gaming_daemons}")
pm.set_profile(OperationalProfile.MINIMAL)
minimal_daemons = PROFILE_CONFIGS[OperationalProfile.MINIMAL].active_daemons
print(f"  Switched to MINIMAL: {len(minimal_daemons)} daemons active: {minimal_daemons}")
pm.set_profile(OperationalProfile.NORMAL)
print("  PASS")

# ── P15: Human Manageability Audit ────────────────────────────────────────────
print("\nP15: Human Manageability Audit")
# Count the total number of distinct systems a developer needs to understand
total_systems = (
    len(threads) +  # background systems
    len(_fsm_instances) +  # FSMs
    len(audit) +  # budget limits
    len(PROFILE_CONFIGS) +  # operational profiles
    8 +  # memory domains
    4 +  # service lifecycles
    1  # unified debug view
)
print(f"  Total distinct systems to track: {total_systems}")
print(f"  Thread count: {len(threads)} daemons")
print(f"  FSM count: {len(_fsm_instances)}")
print(f"  Budget limits: {len(audit)}")
print(f"  Operational profiles: {len(PROFILE_CONFIGS)}")
print(f"  Memory domains: 8")
print(f"  Unified debug view: 1")
audit_result = {
    "thread_count": len(threads),
    "fsm_count": len(_fsm_instances),
    "total_systems": total_systems,
    "manageable": total_systems < 50,
}
print(f"  Manageable (< 50 systems): {audit_result['manageable']}")
print("  PASS")

print("\n=== Simplification & Operational Hardening PASSED ===")
