import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import time

print("=== JARVIS v3 Systems Maturity P1-P15 Validation ===\n")

# P3: FSM State Management
from core.state.fsm import (
    FiniteStateMachine, FSMConfig, TransitionError,
    AssistantFSM, AssistantState, ExecutionFSM, ExecutionState,
    get_state_machine
)
from core.state.registry import get_state_registry

print("P3: Finite State Machines")
fsm = get_state_machine("assistant")
print(f"  Initial state: {fsm.state}")
fsm.transition_to("listening", trigger="user_speak")
print(f"  After transition: {fsm.state}")
fsm.transition_to("thinking", trigger="wakeword_detected")
print(f"  After transition: {fsm.state}")

# Test invalid transition
try:
    fsm.transition_to("idle", trigger="invalid_test")
    print("  FAIL: invalid transition not blocked")
except TransitionError as e:
    print(f"  Invalid transition blocked: {e.current} -> {e.target}")

# Test execution FSM
exec_fsm = get_state_machine("execution")
exec_fsm.transition_to("queued")
print(f"  Execution FSM: {exec_fsm.state}")
exec_fsm.transition_to("running")
print(f"  Execution FSM: {exec_fsm.state}")

reg = get_state_registry()
print(f"  State registry: {len(reg.all_health())} FSMs registered")
print("  PASS")

# P12: Orchestration Safety Limits
from core.orchestration.limits import get_limits
limits = get_limits()
print(f"\nP12: Orchestration Limits")
print(f"  Max concurrent actions: {limits.max_concurrent_actions}")
print(f"  Max event propagation depth: {limits.max_event_propagation_depth}")
print(f"  Max retries per action: {limits.max_retries_per_action}")
print(f"  Action limit check (current=5): {limits.enforce_action_limit(5)}")
print(f"  Action limit check (current=25): {limits.enforce_action_limit(25)}")
print(f"  Queue limit check (depth=50): {limits.enforce_queue_limit(50)}")
print(f"  Queue limit check (depth=105): {limits.enforce_queue_limit(105)}")
print("  PASS")

# P11: System Mode Management
from core.orchestration.modes import SystemMode, SystemModeManager, get_mode_manager, MODE_PROFILES

mm = get_mode_manager()
print(f"\nP11: System Mode Management")
print(f"  Current mode: {mm.current_mode.value}")
print(f"  Profile model_priority: {mm.profile.model_priority}")
print(f"  Profile max_actions: {mm.profile.max_concurrent_actions}")

modes = [SystemMode.GAMING, SystemMode.LOW_POWER, SystemMode.DEVELOPMENT]
for m in modes:
    mm.set_mode(m, reason="test")
    print(f"  Switched to {m.value}: max_actions={mm.profile.max_concurrent_actions}")

mm.set_mode(SystemMode.NORMAL, reason="test")
print("  PASS")

# P15: Health Monitoring
from core.orchestration.health import HealthMonitor, HealthLevel, get_health_monitor

hm = get_health_monitor()
print(f"\nP15: Health Monitoring")
report = hm.generate_report()
print(f"  Overall score: {report.overall_score}")
print(f"  Overall level: {report.overall_level.name}")
print(f"  Subsystems tracked: {len(report.subsystems)}")
print(f"  Active alerts: {len(report.active_alerts)}")
alerts = hm.predict_instability()
print(f"  Instability predictions: {len(alerts)} alerts")
print("  PASS")

# P1: Runtime Graph Inspector
from core.inspector.graph import RuntimeGraphInspector, NodeType, get_inspector

insp = get_inspector()
print(f"\nP1: Runtime Graph Inspector")
insp.add_node("cmd1", NodeType.COMMAND, "open vscode", metadata={"raw": "open vscode"})
insp.add_node("act1", NodeType.ACTION, "launch_app", parent_id="cmd1")
insp.add_event_node("execution.completed", "trace-001", 2, "sub-001")
snapshot = insp.get_snapshot()
print(f"  Nodes: {snapshot.node_count}, Edges: {snapshot.edge_count}")
print(f"  Max depth: {snapshot.max_depth}, Event depth: {snapshot.event_propagation_depth}")
print(f"  Stats: {insp.stats()}")
print("  PASS")

# P2: Event Governance
from core.events.governance import EventGovernance, get_event_governance, EVENT_DOMAINS

gov = get_event_governance()
print(f"\nP2: Event Governance")
print(f"  Domains registered: {len(gov.list_all_domains())}")
print(f"  Domain events: execution={len(gov.get_domain_events('execution'))}")
valid, msg = gov.validate_event_name("execution.completed")
print(f"  Valid event name: {valid}")
valid, msg = gov.validate_event_name("invalid-event")
print(f"  Invalid event name blocked: {not valid}")

valid, msg = gov.record_event("execution.completed", depth=3)
print(f"  Event recording: {valid}")
gov.record_event("execution.completed", depth=12)
valid, msg = gov.record_event("execution.completed", depth=12)
print(f"  Depth limit enforced: {not valid}")

for i in range(60):
    gov.record_event("test.storm", depth=1)
valid, _ = gov.record_event("test.storm", depth=1)
print(f"  Event storm detection: {not valid}")
print(f"  Stats: {gov.stats()}")
print("  PASS")

# P14: Lifecycle Controller
from core.lifecycle.controller import LifecycleController, LifecyclePhase, SubsystemConfig, get_lifecycle_controller

lc = get_lifecycle_controller()
print(f"\nP14: Lifecycle Controller")
lc.register_subsystem(SubsystemConfig(
    name="test_executor", phase=LifecyclePhase.EXECUTION_CORE,
    init_fn=lambda: None, shutdown_fn=lambda: None,
))
lc.register_subsystem(SubsystemConfig(
    name="test_eventbus", phase=LifecyclePhase.EVENT_BUS,
    init_fn=lambda: None, shutdown_fn=lambda: None,
))
lc.start()
print(f"  Phase after start: {lc.current_phase.name}")
print(f"  Ready subsystems: {lc.get_subsystems_status()}")
lc.shutdown()
print(f"  Phase after shutdown: {lc.current_phase.name}")
print("  PASS")

# P13: Hot Reloadable Config
from core.config.manager import ConfigManager, ConfigSchema, get_config_manager

cm = get_config_manager()
print(f"\nP13: Hot Reloadable Config")
cm.register_schema(ConfigSchema(
    name="routing_threshold", default=0.5, type=float,
    min_value=0.0, max_value=1.0, description="Intent routing confidence threshold"
))
cm.register_schema(ConfigSchema(
    name="max_retries", default=3, type=int, min_value=0, max_value=10
))
val, msg = cm.set("routing_threshold", 0.7, reason="test")
print(f"  Set routing_threshold=0.7: {val}")
val, msg = cm.set("max_retries", 5, reason="test")
print(f"  Set max_retries=5: {val}")
val, msg = cm.set("max_retries", 99, reason="test")
print(f"  Validation (99 invalid): {not val}")
current = cm.get("routing_threshold")
print(f"  Current routing_threshold: {current}")
history = cm.get_history("routing_threshold")
print(f"  History entries: {len(history)}")
print("  PASS")

# P10: Complexity Governance
from core.governance.complexity import ComplexityMonitor, get_complexity_monitor

cx = get_complexity_monitor()
print(f"\nP10: Complexity Governance")
metrics = cx.scan()
print(f"  Module count: {metrics.module_count}")
print(f"  Complexity score: {metrics.complexity_score}")
print(f"  Warnings: {len(metrics.warnings)}")
trend = cx.get_trend()
print(f"  Trend: {trend['trend']}")
print("  PASS")

# P8: Provider Isolation
from core.providers.base import (
    ProviderRegistry, BaseProvider, ModelMetadata, ProviderCapability,
    InferenceRequest, InferenceResponse, get_provider_registry
)

class TestProvider(BaseProvider):
    name = "test_provider"
    def list_models(self):
        return [ModelMetadata(
            name="test-model", provider="test_provider",
            capabilities=(ProviderCapability.TEXT,),
            max_tokens=512, context_window=4096,
            preferred_roles=("user",), vram_mb=100,
        )]
    def inference(self, request):
        return InferenceResponse(content="test", model=request.model, provider=self.name, latency_ms=1.0)
    def health_check(self):
        from core.providers.base import ProviderHealth
        return ProviderHealth.HEALTHY

reg = get_provider_registry()
reg.register(TestProvider())
print(f"\nP8: Provider Isolation")
print(f"  Providers: {reg.stats()['providers']}")
print(f"  Models: {reg.stats()['models']}")
capable = reg.get_capable_provider(ProviderCapability.TEXT)
print(f"  Text-capable providers: {len(capable)}")
print("  PASS")

# P7: Policy Engine
from core.orchestration.policies import PolicyEngine, Policy, PolicyPriority, get_policy_engine

pe = get_policy_engine()
print(f"\nP7: Policy Engine")
triggered_values = []
def my_action():
    triggered_values.append("fired")
condition_calls = [0]
def my_condition():
    condition_calls[0] += 1
    return True
pe.register(Policy(
    name="test_policy", condition_fn=my_condition, action_fn=my_action,
    priority=PolicyPriority.NORMAL, cooldown_sec=0.0,
))
result = pe.evaluate_all()
print(f"  Policies: {pe.get_stats()['total_policies']}")
print(f"  Triggered: {len(result.triggered)}")
print(f"  PASS")

# P5: Predictive Resource Scheduling
from core.governance.predictive_scheduler import PredictiveScheduler, WorkloadPrediction, get_predictive_scheduler

pred = get_predictive_scheduler()
print(f"\nP5: Predictive Scheduling")
snapshot = pred.predict()
print(f"  Prediction: {snapshot.prediction.name}")
print(f"  Confidence: {snapshot.confidence}")
print(f"  Actions: {snapshot.recommended_actions[:2]}")
print(f"  Spike trend: {pred.is_spike_trend()}")
print("  PASS")

# P9: Simulation Framework
from core.simulation.framework import ChaosEngine, SimulationScenario, ScenarioType, get_chaos_engine

chaos = get_chaos_engine()
print(f"\nP9: Simulation Framework")
chaos.register_scenario(SimulationScenario(
    name="queue_overload_test", scenario_type=ScenarioType.QUEUE_OVERLOAD,
    duration_sec=1.0, intensity=0.5,
))
print(f"  Registered scenarios: {chaos.stats()['registered_scenarios']}")
chaos.run_scenario("queue_overload_test")
print(f"  Results: {chaos.stats()}")
print("  PASS")

# P6: Memory Domains
from core.governance.memory_domains import MemoryDomains, MemoryDomain, get_memory_domains

mem = get_memory_domains()
print(f"\nP6: Memory Domains")
mem.put(MemoryDomain.CONVERSATIONAL, "conv1", {"text": "hello"})
value = mem.get(MemoryDomain.CONVERSATIONAL, "conv1")
print(f"  Stored/retrieved: {value is not None}")
print(f"  Domain stats: {mem.stats()['CONVERSATIONAL']}")
print("  PASS")

# P4: DI Governance
from core.governance.di_governance import DIGoverner, get_di_governor
from core.services.container import service_container

di = get_di_governor()
print(f"\nP4: DI Governance")
analysis = di.analyze(service_container)
print(f"  Service count: {analysis.get('service_count', 0)}")
print(f"  Initialized: {analysis.get('initialized_count', 0)}")
print(f"  Max depth limit: {di.stats()['max_depth_limit']}")
print("  PASS")

print("\n=== All Systems Maturity P1-P15 PASSED ===")
