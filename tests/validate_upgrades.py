"""
validate_upgrades.py - Tests: ChromaDB persistence, API server, deployment readiness
"""
import sys, io, os, time, threading, json, socket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = []
FAIL = []
def ok(n):      PASS.append(n); print(f"  [PASS]  {n}")
def fail(n, e): FAIL.append(n); print(f"  [FAIL]  {n}: {e}")

SEP = "=" * 52
print(f"\n{SEP}")
print("  JARVIS Upgrade Validation Suite")
print(f"{SEP}")

# ── 1. ChromaDB Persistence ───────────────────────────────────────────────────
print("\n[ 1 ] ChromaDB Vector Persistence")
try:
    from core.tools.long_term_memory import LongTermMemory
    db = LongTermMemory()

    # Use the real API: commit_memory / search_memory
    db.commit_memory("deploy portfolio to vercel",
                     "Scaffold HTML -> HTTP preflight -> git init -> vercel deploy")
    db.commit_memory("morning coding mode setup",
                     "User opens VSCode + Spotify + terminal at 9am daily")
    del db

    import gc; gc.collect()
    time.sleep(0.3)

    db2 = LongTermMemory()
    r = db2.search_memory("vercel portfolio deployment", limit=1)
    assert "Vercel" in r or "vercel" in r.lower() or "HTML" in r, f"Expected content in: {r[:80]}"

    r2 = db2.search_memory("morning routine open apps", limit=1)
    assert "VSCode" in r2 or "9am" in r2 or "Spotify" in r2, f"Got: {r2[:80]}"

    ok(f"ChromaDB: records persist across restarts ({len(r)} chars in result)")
except Exception as e:
    fail("ChromaDB persistence", e)

# ── 2. API Server WebSocket (real connection test) ────────────────────────────
print("\n[ 2 ] JarvisAPIServer WebSocket LAN Control")
try:
    import websockets
    ok("websockets package available")

    from core.api.api_server import JarvisAPIServer

    class MockBrain:
        def process(self, cmd): return f"Executed: {cmd}"

    srv = JarvisAPIServer(brain=MockBrain(), port=8767)  # use fresh port
    srv.start_async()
    time.sleep(1.5)

    # Test with sync websocket client using a dedicated thread+loop
    results = {}

    def _ws_test():
        import asyncio, websockets

        async def _client():
            token = srv._token
            async with websockets.connect("ws://127.0.0.1:8767", open_timeout=5) as ws:
                # Auth
                await ws.send(json.dumps({"type": "auth", "token": token}))
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                results["auth"] = msg["type"]  # "auth"

                # Drain welcome status message
                welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                # welcome is {"type": "status", "text": "JARVIS online..."}

                # Ping — now next message is pong
                await ws.send(json.dumps({"type": "ping"}))
                pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                results["ping"] = pong["type"]  # "pong"

                # Command — server sends status then response
                await ws.send(json.dumps({"type": "command", "text": "open chrome"}))
                _ = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))     # "status: Processing..."
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))  # "response: Executed..."
                results["cmd"] = resp["text"]


        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_client())
        finally:
            loop.close()

    t = threading.Thread(target=_ws_test, daemon=True)
    t.start()
    t.join(timeout=10)

    assert results.get("auth") == "auth",  f"Auth failed: {results}"
    assert results.get("ping") == "pong",  f"Ping failed: {results}"
    assert "Executed" in results.get("cmd", ""), f"Command failed: {results}"

    srv.stop()
    ok(f"WebSocket: auth+ping+command PASS | '{results['cmd']}'")
except Exception as e:
    fail("API server WebSocket", e)

# ── 3. Broadcast hook (agent step → connected phones) ─────────────────────────
print("\n[ 3 ] API Broadcast (agent step → LAN clients)")
try:
    from core.api.api_server import JarvisAPIServer
    class MockBrain:
        def process(self, cmd): return "ok"
    srv2 = JarvisAPIServer(brain=MockBrain(), port=8768)
    srv2.start_async()
    time.sleep(0.5)
    # Broadcast without clients — should not crash
    srv2.broadcast("status", "Step 1/5: write_file")
    srv2.broadcast("status", "Step 2/5: git_commit")
    srv2.stop()
    ok("Broadcast call with no clients: no crash")
except Exception as e:
    fail("API broadcast", e)

# ── 4. Gesture Engine ─────────────────────────────────────────────────────────
print("\n[ 4 ] Gesture Engine")
try:
    import mediapipe as mp
    ok(f"mediapipe {mp.__version__} — hand gesture model available")
except ImportError as e:
    fail("mediapipe", e)

# ── 5. LAN connectivity info ──────────────────────────────────────────────────
print("\n[ 5 ] LAN Remote Control Addresses")
try:
    lan_ip = socket.gethostbyname(socket.gethostname())
    print(f"  Phone WebSocket URL: ws://{lan_ip}:8765")
    print(f"  Auth header:         Authorization: Bearer <token printed at startup>")
    print(f"  JSON protocol:")
    print('    Send: {"type": "auth",    "token": "<token>"}')
    print('    Send: {"type": "command", "text":  "open chrome"}')
    print('    Recv: {"type": "response","text":  "Opening Chrome, sir."}')
    ok(f"LAN IP resolved: {lan_ip}")
except Exception as e:
    fail("LAN IP", e)

# ── 6. Smoke test still green ─────────────────────────────────────────────────
print("\n[ 6 ] Core Smoke Test (quick sanity check)")
try:
    from core.tools import dispatch_tool
    r = dispatch_tool("shell", "echo jarvis-ok", "owner")
    assert "jarvis-ok" in r
    from core.agent.agent import JarvisAgent, is_agentic_command
    assert is_agentic_command("build a portfolio site")
    assert not is_agentic_command("open chrome")
    ok("Dispatch + AgentRouter still working")
except Exception as e:
    fail("Core smoke test", e)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  RESULTS:  {len(PASS)} passed  /  {len(FAIL)} failed")
if FAIL:
    print(f"  FAILED:   {', '.join(FAIL)}")
else:
    print("  All upgrade validations PASS. JARVIS is mission-ready.")
print(f"{SEP}\n")
