import os
import sys
import threading
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.system.docker_sandbox import get_sandbox
from core.providers.ollama_manager import OllamaManager
from core.agent.agent_cluster import get_cluster
from core.agent.jarvis_brain import JarvisBrain

def audit_v3():
    print("=== JARVIS-V3 DEEP AUDIT ===")
    
    # 1. Verify Docker Sandbox Hardening
    print("\n1. Auditing Docker Sandbox...")
    sandbox = get_sandbox()
    # Check if host fallback methods are actually gone
    if hasattr(sandbox, "_host_python") or hasattr(sandbox, "_host_shell"):
        print("  FAIL: Host fallback methods still exist in DockerSandbox!")
    else:
        print("  PASS: Host fallback methods removed.")
    
    status = sandbox.status()
    if "Host execution fallback is DISABLED" in status:
        print("  PASS: Sandbox status reports hardening.")
    else:
        print("  FAIL: Sandbox status does not reflect hardening.")

    # 2. Verify Agent Cluster (YAML)
    print("\n2. Auditing Agent Cluster...")
    cluster = get_cluster()
    architect_model = cluster.get_model_for_role("architect_subagent")
    execution_model = cluster.get_model_for_role("execution_subagent")
    auditor_model   = cluster.get_model_for_role("security_auditor")
    
    print(f"  Architect: {architect_model}")
    print(f"  Execution: {execution_model}")
    print(f"  Auditor:   {auditor_model}")
    
    if "deepseek-r1" in architect_model or "qwen" in execution_model or "gemma" in auditor_model:
         print("  PASS: Agent cluster correctly parsed agent.yaml.")
    else:
         print("  FAIL: Agent cluster models look hardcoded or default.")

    # 3. Verify VRAM Guardian (Ollama)
    print("\n3. Auditing VRAM Guardian...")
    om = OllamaManager()
    if hasattr(om, "switch_model") and hasattr(om, "unload_all"):
        print("  PASS: OllamaManager has proactive VRAM methods.")
    else:
        print("  FAIL: OllamaManager missing VRAM management methods.")

    # 4. Verify security and VRAM pipeline hooks that exist in the current architecture.
    print("\n4. Auditing Brain Pipeline...")
    brain = JarvisBrain(identity="audit_tester")
    import inspect
    from core.agent.agent import JarvisAgent
    from core.system import security

    agent_source = inspect.getsource(JarvisAgent.run)
    if hasattr(security, "vibe_shield_middleware") and "switch_model" in agent_source:
        print("  PASS: VibeShield module available and VRAM switching wired into Agent pipeline.")
    else:
        print("  FAIL: Security/VRAM pipeline hooks missing.")

    # 5. Verify Proactive Assistance
    if hasattr(brain, "_handle_system_alert") and hasattr(brain, "_proactive_code_check"):
        print("  PASS: Proactive code health monitoring implemented.")
    else:
        print("  FAIL: Proactive methods missing in Brain.")

    print("\n=== AUDIT COMPLETE ===")

if __name__ == "__main__":
    audit_v3()
