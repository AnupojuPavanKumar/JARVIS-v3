# core/agent.py  --  JARVIS AUTONOMOUS AGENT  (ReAct Loop)
import sys, io
# Force UTF-8 stdout on Windows to avoid cp1252 UnicodeEncodeError on box-drawing chars
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
# ──────────────────────────────────────────────────────────────────────────────
# Uses qwen2.5-coder:7b (4.7GB VRAM, fits RTX 4050 6GB) via Ollama for
# structured JSON planning. Executes real tools in a loop until task completion.
# ModelRouter selects the best model per task; WorkspaceManager isolates
# each project into its own Desktop directory.
# ──────────────────────────────────────────────────────────────────────────────

import json
import re
import datetime
import os
import time
import requests
import logging
from typing import Optional

from core.system.workspace_manager import get_workspace_manager
from core.providers.model_router import get_router as get_model_router
from core.engines.persona_engine import get_persona_engine
from core.system.observability import get_observability
from core.testing.failure_injector import get_failure_injector

# ── Model config ────────────────────────────────────────────────────────────────────────────────
OLLAMA_URL     = "http://localhost:11434/api/chat"
OLLAMA_HEALTH  = "http://localhost:11434/api/tags"   # Fast health-check endpoint
AGENT_MODEL    = "qwen2.5-coder:7b"   # Primary: code-tuned, 4.7GB VRAM, fits RTX 4050 6GB
FALLBACK_MODEL = "llama3.2:3b"        # Fallback: fast 2GB chat model

MAX_STEPS    = 40   # Hard cap per task
LLM_TIMEOUT  = 180  # Seconds per Ollama request (bumped for cold-start VRAM pressure)

# Circuit breaker: retry config
_CB_MAX_RETRIES  = 3          # Max attempts per model
_CB_BACKOFF      = [0, 5, 10]  # Seconds to wait before each attempt (0 = immediate first try)

# Resolve actual user desktop at import time (DEF-003 fix)
USER_DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop").replace("\\", "/")

# ── System prompt ─────────────────────────────────────────────────────────────
AGENT_SYSTEM_PROMPT_TEMPLATE = """You are JARVIS V3 -- Senior Systems Architect. Execute tasks autonomously using Plan-and-Execute (P&E) logic. Deploy in minutes, not weeks.

RESPONSE FORMAT: Reply with valid JSON only.
{
  "thought": "Reasoning for the next step",
  "action": "<tool_name>",
  "input": "<tool_input>"
}

FINISH FORMAT (Task complete or Refused):
{
  "thought": "Refusing unsafe/impossible task OR task is finished.",
  "action": "finish",
  "output": "<Natural spoken summary for the user, addressed as 'sir'>"
}

RULES & CONSTRAINTS:
1.  PLANNING: Outline file structure in 'thought' or PLAN.md before complex projects.
2.  SAFETY: NEVER touch C:/Windows or Program Files. Use 'finish' to refuse.
3.  WORKSPACE: Build ONLY in {desktop} or user-specified paths. NEVER inside JARVIS-v3.
4.  FILE OPS: Use 'map_structure' to scan. Use 'replace_in_file' for surgical edits (no full rewrites).
5.  TDD: You MUST write and run tests before calling 'finish'. Exit code 0 is mandatory.
6.  WEB/UI: Senior Dev Protocol: Glassmorphism, HSL gradients, Google Fonts, SEO-ready HTML5.
7.  RESEARCH: Use 'web_research' for complex data gathering. It summarizes multi-page results locally.
8.  SERVERS: Use 'npx -y'. Verify ports via 'read_shell_output' and validate '200 OK' before 'open_url'.
9.  DEPLOY: Use 'git_pipeline'. ALWAYS pre-flight validate (local test) before deploying.
10. DEBUG: If a tool fails, IMMEDIATELY call 'diagnose_error' on the traceback.
11. RESILIENCE: After 3 failed attempts with one tool, switch strategy completely.
12. FEEDBACK: Use 'notify' for key milestones (e.g., "Tests passed", "Deploying now").
13. CONCISE: Be efficient. Finish in as few steps as possible. Spoken output should be natural.
"""


class JarvisAgent:
    """
    Autonomous task execution agent using the ReAct (Reason + Act) loop.
    Instantiated once at startup and reused across sessions.
    """

    def __init__(self, identity: str = "owner", ui=None):
        self.identity   = identity
        self.ui         = ui
        self._log_file  = "memory/agent_log.jsonl"
        self._model     = AGENT_MODEL
        # Build runtime system prompt with actual desktop path (DEF-003 fix)
        self._system_prompt = AGENT_SYSTEM_PROMPT_TEMPLATE.replace(
            "{desktop}", USER_DESKTOP
        )
        # Inject Persona
        persona = get_persona_engine()
        self._system_prompt += "\n" + persona.get_context_prompt()
        os.makedirs("memory", exist_ok=True)
        print(f"[AGENT] Initialized | model={self._model} | desktop={USER_DESKTOP}")

    # ── Public API ─────────────────────────────────────────────────────────────
    def run(self, task: str) -> str:
        """
        Execute a task autonomously.
        Returns a plain-English spoken result for JARVIS to speak.
        """
        from core.tools import dispatch_tool
        from core.agent.self_learning import get_learning_loop
        _learning = get_learning_loop()

        scratchpad   : list[dict] = []
        steps_taken  : int        = 0
        fail_streak  : int        = 0   # consecutive tool failures
        _learning.on_task_start(task)
        start_time               = datetime.datetime.now()

        print(f"\n[AGENT] === NEW TASK ===")
        print(f"[AGENT] {task}")

# ── VRAM Guard: evict stale models if VRAM is overloaded ────────────────
        try:
            from core.providers.ollama_manager import get_ollama_manager
            _om = get_ollama_manager()
            _om.warn_if_vram_critical(threshold_pct=75.0)
        except Exception as e:
            logging.error(f"[AGENT] VRAM check error: {e}")

        # ── Model Selection (Simplified for deterministic execution) ───────────────
        try:
            from core.providers.ollama_manager import get_ollama_manager
            router = get_model_router()
            selected_model = router.route(task)
            if selected_model != self._model:
                print(f"[AGENT] ModelRouter: '{selected_model}' selected.")
            self._model = selected_model
            get_ollama_manager().switch_model(self._model)
        except Exception as e:
            print(f"[AGENT] ModelRouter error ({e}) — using default model: {self._model}")

        # ── Create isolated workspace for this task ─────────────────────────────
        task_workspace = None
        try:
            dev_task_words = {"build", "create", "make", "scaffold", "generate", "develop", "write", "script", "app"}
            if any(w in task.lower() for w in dev_task_words):
                ws_mgr = get_workspace_manager()
                # Try to extract an explicit folder name from quoted strings in the task
                import re as _re
                quoted = _re.findall(r"['\"]([A-Za-z0-9_\-]{3,50})['\"]", task)
                if quoted:
                    ws_name = quoted[0]  # Use the first quoted identifier as the folder name
                else:
                    ws_name = task[:60]  # Fall back to truncated task text
                task_workspace = ws_mgr.create(ws_name)
                print(f"[AGENT] Workspace: {task_workspace}")
        except Exception as e:
            print(f"[AGENT] WorkspaceManager error ({e}) -- proceeding without isolated workspace.")

        # ── Inject workspace context into system prompt if applicable ───────────
        effective_system = self._system_prompt
        if task_workspace:
            effective_system += (
                f"\n\nWORKSPACE CONTEXT: This task has an isolated project directory at: {task_workspace}\n"
                f"ALL new project files MUST be written inside this workspace directory.\n"
                f"Do NOT write project files into the JARVIS system directory.\n"
            )

        # ── Context Persistence (Layered Memory) ──
        try:
            from core.memory.layered_memory import get_layered_memory
            memories = get_layered_memory().retrieve(query_tags=[task.split()[0].lower()], max_results=2)
            procedural = [m.content for m in memories if m.layer == "procedural"]
            if procedural:
                effective_system += (
                    f"\n\nHISTORIC PATTERN MATCHES (Procedural Memory):\n"
                    f"You have successfully solved similar tasks in the past. "
                    f"Use these patterns to guide your current scaffolding:\n"
                    + "\n\n".join(procedural)
                )
        except Exception as e:
            print(f"[Agent] Memory retrieval error: {e}")

        # ── Store active (workspace-enriched) system prompt for this run ───────
        self._active_system = effective_system

        # ── Inject golden patterns from self-learning (Upgrade #8) ──────────
        try:
            golden = _learning.recall_patterns(task)
            if golden:
                self._active_system += f"\n\n{golden}\n"
                print(f"[AGENT] Self-learning: {len(golden)} chars of golden patterns injected.")
        except Exception:
            pass

        # Inject developer mode context based on the task phrasing
        dev_trigger_phrases = ["build", "code", "develop", "script", "program", "app"]
        if any(phrase in task.lower() for phrase in dev_trigger_phrases):
            scratchpad.append({
                "thought": "Entering High-intelligence mode.",
                "action": "internal_retry",
                "input": "",
                "observation": "System Context Update: Sir is in Developer Mode. High-intelligence parameters engaged."
            })
            print(f"[AGENT] Developer parameters engaged.")

        while steps_taken < MAX_STEPS:
            # ── Scratchpad Truncation: Programmatic sliding window (VRAM-safe) ──
            if len(scratchpad) > 15:
                # Keep first step (init) and last 8 steps verbatim
                old_steps  = scratchpad[1:-8]
                keep_steps = scratchpad[-8:]

                # Fast heuristic summary (no LLM required, zero VRAM overhead)
                summary_lines = ["[PRIOR CONTEXT TRUNCATED] Action History:"]
                for i, s in enumerate(old_steps, 1):
                    if s.get("action") == "internal_retry": continue
                    # Extract high-signal data only
                    line = f"- Step {i}: {s.get('action','?')} -> {str(s.get('observation',''))[:100]}..."
                    summary_lines.append(line)

                summarized = {
                    "thought":     "Context compressed to preserve working memory.",
                    "action":      "internal_retry",
                    "input":       "",
                    "observation": "\n".join(summary_lines)
                }
                scratchpad = [scratchpad[0], summarized] + keep_steps
                print(f"[AGENT] Scratchpad compressed: {len(old_steps)} steps → Heuristic summary.")

            steps_taken += 1

            # ── Build LLM messages ─────────────────────────────────
            messages = self._build_messages(task, scratchpad)

            # ── Emit real-time step status to HUD, UI, and LAN clients ─────────
            # Shows "Step 3/12: write_file" live in HUD panel + API clients.
            try:
                tool_hint = ""
                if scratchpad:
                    last = scratchpad[-1]
                    tool_hint = last.get('action', '')
                step_label = f"[Agent Step {steps_taken}{(' -> ' + tool_hint) if tool_hint else ''}]"

                # ── Route through TelemetryService (weakref-safe, no dead-widget risk) ──
                try:
                    from core.agent.telemetry_service import get_telemetry_service
                    _telem = get_telemetry_service()
                    _telem.set_agent_step(steps_taken, MAX_STEPS, tool_hint or "thinking")
                    _telem.set_active_skill(step_label)
                except Exception as _te:
                    logging.debug(f"[Agent] TelemetryService update skipped: {_te}")

                # ── API broadcast → phones / tablets on LAN ─────────────
                try:
                    # Lazy singleton — grab the running API server if started
                    import importlib
                    _api_mod = importlib.import_module('core.api.api_server')
                    _api_inst = getattr(_api_mod, '_running_server', None)
                    if _api_inst is not None:
                        _api_inst.broadcast("agent_step", {
                            "step":   steps_taken,
                            "action": tool_hint or "thinking",
                            "label":  step_label
                        })
                except Exception as e:
                    logging.error(f"Silent error caught (API broadcast): {e}")

            except Exception as e:
                logging.error(f"Silent error caught (UI status): {e}")


            # ── Call LLM ───────────────────────────────────────────
            raw_reply = self._call_llm(messages)

            if raw_reply is None:
                return ("I couldn't reach my inference engine, sir. "
                        "Please ensure Ollama is running.")

            # ── Parse JSON action ──────────────────────────────────
            action_data = self._parse_json(raw_reply)

            if not action_data:
                print(f"[AGENT] JSON parse failed on step {steps_taken}. Raw: {raw_reply[:200]}")
                fail_streak += 1
                if fail_streak >= 3:
                    return "I encountered repeated formatting errors in my reasoning, sir. Please try again."
                # Inject a recovery hint and retry
                scratchpad.append({
                    "thought": "My previous response had a JSON formatting error.",
                    "action": "internal_retry",
                    "input": "",
                    "observation": "JSON parse failed. You MUST respond with valid JSON only."
                })
                continue

            fail_streak = 0  # reset on successful parse

            thought = action_data.get("thought", "")
            action  = action_data.get("action",  "finish")

            # CHAOS INJECTION: Hallucinated Tool
            if get_failure_injector().should_inject("model", "hallucinated_tool"):
                action = "tool_does_not_exist_chaos_test"
                print(f"[AGENT] [CHAOS] Injected hallucinated tool: {action}")

            print(f"[AGENT] Step {steps_taken:02d} | {action.upper()}")
            print(f"[AGENT]         Thought: {thought[:100]}")
            
            get_observability().log_decision(
                component="JarvisAgent",
                action=action,
                rationale=thought
            )

            # ── FINISH ─────────────────────────────────────────────
            if action == "finish":
                output = action_data.get("output", "Task completed, sir.")
                self._log(task, scratchpad, output, start_time)
                print(f"[AGENT] === TASK COMPLETE in {steps_taken} steps ===\n")
                # Self-learning: store as golden pattern
                _learning.on_task_complete(task, output, steps_taken, success=True)
                # Auto-evict models from VRAM after task complete
                try:
                    from core.providers.ollama_manager import get_ollama_manager
                    get_ollama_manager().evict_models()
                except Exception:
                    pass
                return output

            # ── Execute tool ───────────────────────────────────────
            tool_input = action_data.get("input", "")
            print(f"[AGENT]         Input:   {str(tool_input)[:120]}")

            observation = dispatch_tool(action, tool_input, self.identity)
            _learning.on_tool_call(action)   # track which tools are used

            print(f"[AGENT]         Observe: {str(observation)[:150]}")

            # Track failure streak for tool errors
            is_failure = (
                isinstance(observation, str) and 
                (observation.startswith(("[BLOCKED]", "[DENIED]", "Tool Error:", "Tool dispatch error", "[SECURITY ERROR]", "[SANDBOX ERROR]", "[TIMEOUT]")) or
                 "[Process EXITED with code" in observation)
            )

            if is_failure:
                fail_streak += 1
                
                # Auto-diagnosis via GhostDebugger if not already diagnosing
                if action != "diagnose_error":
                    print(f"[AGENT] Auto-diagnosing failure in {action}...")
                    try:
                        diagnosis = dispatch_tool("diagnose_error", observation, self.identity)
                        observation = f"{observation}\n\n[AUTO-DIAGNOSIS]: {diagnosis}"
                    except Exception as diag_err:
                        print(f"[AGENT] Auto-diagnosis failed: {diag_err}")

                # Ask self-learning for an auto-heal suggestion after 3 failures
                heal_hint = _learning.on_tool_failure(
                    task, action, observation, fail_streak
                )
                if heal_hint:
                    print(f"[AGENT] {heal_hint}")
                    scratchpad.append({
                        "thought":     "Auto-heal suggestion from self-learning.",
                        "action":      "internal_retry",
                        "input":       "",
                        "observation": heal_hint
                    })
            else:
                fail_streak = 0

            scratchpad.append({
                "thought":     thought,
                "action":      action,
                "input":       str(tool_input),
                "observation": str(observation)
            })

        # ── Max steps hit ──────────────────────────────────────────
        done_actions = [s["action"] for s in scratchpad]
        summary = (
            f"I reached my step limit working on your task, sir. "
            f"I completed {len(scratchpad)} steps including: "
            f"{', '.join(set(done_actions))}. "
            f"The task may be partially complete."
        )
        self._log(task, scratchpad, summary, start_time)
        _learning.on_task_complete(task, summary, steps_taken, success=False)
        return summary

    # ── LLM integration ────────────────────────────────────────────────────────
    def _build_messages(self, task: str, scratchpad: list) -> list:
        # Use the per-run active system prompt (may include workspace context)
        active_prompt = getattr(self, '_active_system', self._system_prompt)
        messages = [{"role": "system", "content": active_prompt}]

        user_ctx = f"TASK: {task}\n\n"

        if scratchpad:
            user_ctx += "EXECUTION HISTORY:\n"
            for i, step in enumerate(scratchpad, 1):
                if step.get("action") == "internal_retry":
                    user_ctx += f"\n[Step {i}] SYSTEM: {step['observation']}\n"
                    continue
                user_ctx += (
                    f"\n[Step {i}]\n"
                    f"  Thought     : {step['thought']}\n"
                    f"  Action      : {step['action']}\n"
                    f"  Input       : {str(step['input'])[:200]}\n"
                    f"  Observation : {str(step['observation'])[:400]}\n"
                )
            user_ctx += "\nNow decide the NEXT action. Reply with valid JSON only."
        else:
            user_ctx += "Begin executing this task. Reply with valid JSON only."

        messages.append({"role": "user", "content": user_ctx})
        return messages

    def _call_llm(self, messages: list) -> Optional[str]:
        """Call Ollama with the agent model, retrying with exponential backoff.
        Falls back to llama3 if qwen2.5 is unavailable.
        Returns None only if ALL models fail ALL retries.
        """
        from core.providers.ollama_manager import get_ollama_manager
        ollama = get_ollama_manager()

        # Fast pre-flight check — avoids 90s timeout if Ollama is completely down
        if not ollama.is_running():
            print("[AGENT] Ollama health check failed — server may be down.")
            return None

        for model in (self._model, FALLBACK_MODEL):
            for attempt in range(_CB_MAX_RETRIES):
                wait = _CB_BACKOFF[attempt]
                if wait > 0:
                    print(f"[AGENT] Retry {attempt}/{_CB_MAX_RETRIES - 1} for {model} — waiting {wait}s...")
                    time.sleep(wait)

                try:
                    content = ollama.chat(
                        model=model,
                        messages=messages,
                        options={
                            "temperature":    0.05,
                            "top_p":          0.9,
                            "repeat_penalty": 1.1,
                            "num_ctx":        16384,
                            "num_predict":    4096,
                            "stop":           ["---"]
                        },
                        timeout=LLM_TIMEOUT
                    )

                    if content:
                        if model != self._model:
                            print(f"[AGENT] Using fallback model: {model}")
                        return content

                except Exception as e:
                    print(f"[AGENT] LLM call error: {e}")

        print("[AGENT] All models and retries exhausted.")
        return None

    def _parse_json(self, raw: str) -> Optional[dict]:
        """Robustly parse the LLM's JSON response."""
        # CHAOS INJECTION: Malformed JSON
        if get_failure_injector().should_inject("model", "malformed_json"):
            raw = '{"thought": "chaos", "action": "missing_quotes, input: }'
            print("[AGENT] [CHAOS] Injected malformed JSON.")
            
        raw = raw.strip()

        # Direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Strip markdown fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to extract first JSON object
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    # ── Logging ────────────────────────────────────────────────────────────────
    def _log(self, task: str, scratchpad: list, result: str, start_time: datetime.datetime):
        try:
            entry = {
                "timestamp":  start_time.isoformat(),
                "task":       task,
                "steps":      len(scratchpad),
                "actions":    [s.get("action") for s in scratchpad if s.get("action") != "internal_retry"],
                "result":     result,
                "duration_s": round((datetime.datetime.now() - start_time).total_seconds(), 2)
            }
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[AGENT] Logging error: {e}")


# ── Agentic trigger detection ──────────────────────────────────────────────────
# Commands matching these phrases are routed to the agent instead of CommandEngine.
# Phrases are chosen to indicate multi-step "do something" tasks vs. quick lookups.

AGENT_TRIGGER_PHRASES = {
    # Creation
    "build", "create a", "make a", "generate a", "write a", "develop a",
    "scaffold", "set up a", "setup a", "initialize a", "init a",
    "build an app", "build fullstack", "build me a", "open a tab",
    # Code / Scripts
    "script that", "program that", "code that", "tool that", "bot that",
    "write code", "write python", "write script",
    # File/System Operations
    "rename all", "delete all", "move all", "copy all", "compress",
    "backup", "archive", "find all", "list all files",
    # Automation
    "automate", "schedule", "monitor", "track", "watch",
    # Data
    "analyze", "analyse", "summarize", "summarise",
    "extract", "convert", "process", "parse", "scrape",
    # Fetch / Download
    "download and", "fetch and", "get me the", "grab the",
    # Deployment
    "install", "configure", "deploy", "run a server",
}


def is_agentic_command(command: str) -> bool:
    """Return True if the command should be handled by JarvisAgent."""
    cmd = command.lower().strip()

    # Must be long enough to be a real task (>= 3 words).
    # 4 was too strict — "build an app" (3 words) would silently fall through.
    if len(cmd.split()) < 3:
        return False

    return any(phrase in cmd for phrase in AGENT_TRIGGER_PHRASES)
