# core/api_server.py — JARVIS WEBSOCKET API SERVER
# ──────────────────────────────────────────────────────────────────────────────
# Exposes JARVIS to any device on the LAN via WebSocket.
# Phone app, browser dashboard, or any script can send/receive commands.
#
# Protocol:
#   Client → Server:  {"type": "command", "text": "open chrome"}
#   Server → Client:  {"type": "response", "text": "Opening Chrome, sir."}
#   Server → Client:  {"type": "status",   "text": "Listening"}
#   Server → Client:  {"type": "error",    "text": "..."}
#
# Auth: token-based. Set JARVIS_API_TOKEN env var or it auto-generates one.
# Run: api_server.start_async(brain) — non-blocking, runs in background thread.
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
import json
import os
import threading
import secrets
import datetime
import websockets
from websockets.server import WebSocketServerProtocol


API_PORT  = int(os.environ.get("JARVIS_API_PORT",  "8765"))
# Default to LAN-accessible binding; callers can still override via env var.
API_HOST  = os.environ.get("JARVIS_API_HOST", "0.0.0.0")
API_TOKEN = os.environ.get("JARVIS_API_TOKEN", "")

# Auto-generate token if not set and print to console (one-time)
if not API_TOKEN:
    API_TOKEN = secrets.token_hex(16)
    # Do NOT print the token in plain-text — write it to a file the user can read.
    _token_file = os.path.join("memory", "api_token.txt")
    try:
        os.makedirs("memory", exist_ok=True)
        with open(_token_file, "w") as _f:
            _f.write(API_TOKEN)
        print(f"[API] Session token saved to: {_token_file}")
        print(f"[API] Connect: ws://{API_HOST}:{API_PORT}")
        print(f"[API] Header:  Authorization: Bearer <see {_token_file}>")
    except Exception:
        # Fallback: print to console if file write fails
        print(f"[API] Generated session token (could not write to file): {API_TOKEN}")
        print(f"[API] Connect: ws://{API_HOST}:{API_PORT}")

# Module-level singleton — set by start_async() so agent.py can broadcast
_running_server = None


class JarvisAPIServer:
    """
    LAN WebSocket server — lets any device send commands to JARVIS.
    Non-blocking: starts in a dedicated daemon thread with its own event loop.
    """

    def __init__(self, brain, port: int = API_PORT):
        self._brain    = brain
        self._port     = port
        self._clients  : set[WebSocketServerProtocol] = set()
        self._loop     : asyncio.AbstractEventLoop | None = None
        self._thread   : threading.Thread | None = None
        self._running  = False
        self._token    = API_TOKEN

    # ── Start ──────────────────────────────────────────────────────────────────
    def start_async(self):
        """Start the server in a background daemon thread."""
        global _running_server
        if self._running:
            return
        self._running  = True
        self._thread   = threading.Thread(target=self._run_loop, daemon=True, name="JarvisAPI")
        self._thread.start()
        _running_server = self
        print(f"[API] WebSocket server starting on port {self._port}...")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[API] Server error: {e}")
        finally:
            self._loop.close()

    async def _serve(self):
        self._stop_event = asyncio.Event()
        # Start background telemetry broadcast (Upgrade #8)
        asyncio.create_task(self._telemetry_loop())
        
        async with websockets.serve(
            self._handler,
            API_HOST,
            self._port,
            ping_interval=30,
            ping_timeout=10,
            max_size=1_048_576,
        ):
            print(f"[API] Server live on ws://{API_HOST}:{self._port}")
            await self._stop_event.wait()

    async def _telemetry_loop(self):
        """Periodically broadcast system health to all connected dashboards."""
        from core.system.hardware_sentinel import get_hardware_sentinel
        while not self._stop_event.is_set():
            try:
                sentinel = get_hardware_sentinel()
                if sentinel:
                    stats = sentinel.get_stats()
                    self.broadcast("telemetry", stats)
            except Exception as e:
                print(f"[API] Telemetry broadcast error: {e}")
            await asyncio.sleep(4)

    # ── Connection handler ─────────────────────────────────────────────────────
    async def _handler(self, ws: WebSocketServerProtocol):
        # Auth handshake
        if not await self._authenticate(ws):
            return

        self._clients.add(ws)
        addr = ws.remote_address
        print(f"[API] Client connected: {addr}")

        # Send welcome
        await self._send(ws, "status", "JARVIS online. Ready for your commands, sir.")

        try:
            async for raw in ws:
                await self._handle_message(ws, raw)
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except Exception as e:
            print(f"[API] Client error from {addr}: {e}")
        finally:
            self._clients.discard(ws)
            print(f"[API] Client disconnected: {addr}")

    async def _authenticate(self, ws: WebSocketServerProtocol) -> bool:
        """Expect first message to be auth token."""
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("type") == "auth" and msg.get("token") == self._token:
                await self._send(ws, "auth", "Authenticated. Welcome, sir.")
                return True
            await self._send(ws, "error", "Authentication failed.")
            await ws.close()
            return False
        except asyncio.TimeoutError:
            await ws.close()
            return False
        except Exception:
            await ws.close()
            return False

    async def _handle_message(self, ws: WebSocketServerProtocol, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(ws, "error", "Invalid JSON.")
            return

        msg_type = msg.get("type", "")

        if msg_type == "command":
            text = msg.get("text", "").strip()
            if not text:
                await self._send(ws, "error", "Empty command.")
                return

            await self._send(ws, "status", f"Processing: {text}")
            print(f"[API] Command from {ws.remote_address}: {text}")

            # Run brain.process in executor (it's blocking)
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: self._brain.process(text)
                )
                await self._send(ws, "response", result or "Done, sir.")
            except Exception as e:
                await self._send(ws, "error", f"Processing error: {e}")

        elif msg_type == "get_telemetry":
            from core.system.hardware_sentinel import get_hardware_sentinel
            sentinel = get_hardware_sentinel()
            if sentinel:
                await self._send(ws, "telemetry", sentinel.get_stats())
            else:
                await self._send(ws, "error", "Telemetry unavailable.")

        elif msg_type == "get_memory":
            try:
                # Returns 5 recent conversation turns and 5 knowledge graph entries
                memory = getattr(self._brain, "memory", None) or getattr(self._brain, "_mem", None)
                if memory is None:
                    raise RuntimeError("Memory service is not available.")
                recent_conv = memory.get_recent(5)
                recent_graph = memory.search_graph("")[:5]
                await self._send(ws, "memory_data", {
                    "conversation": recent_conv,
                    "graph": recent_graph
                })
            except Exception as e:
                await self._send(ws, "error", f"Memory fetch error: {e}")

        elif msg_type == "ping":
            await self._send(ws, "pong", datetime.datetime.now().isoformat())

        elif msg_type == "status":
            await self._send(ws, "status", "JARVIS online.")

        else:
            await self._send(ws, "error", f"Unknown message type: {msg_type}")

    async def _send(self, ws: WebSocketServerProtocol, msg_type: str, data: any):
        try:
            payload = {
                "type": msg_type,
                "ts":   datetime.datetime.now().isoformat()
            }
            if isinstance(data, str):
                payload["text"] = data
            else:
                payload["data"] = data
            await ws.send(json.dumps(payload))
        except Exception:
            pass

    # ── Broadcast ──────────────────────────────────────────────────────────────
    def broadcast(self, msg_type: str, data):
        """Thread-safe broadcast to all connected clients."""
        if not self._clients or self._loop is None:
            return
        
        payload_dict = {
            "type": msg_type,
            "ts":   datetime.datetime.now().isoformat()
        }
        if isinstance(data, str):
            payload_dict["text"] = data
        else:
            payload_dict["data"] = data
            
        payload = json.dumps(payload_dict)
        
        async def _bcast():
            for ws in list(self._clients):
                try:
                    await ws.send(payload)
                except Exception:
                    pass
        asyncio.run_coroutine_threadsafe(_bcast(), self._loop)

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            # Signal the _serve() coroutine to exit cleanly
            if hasattr(self, '_stop_event') and self._stop_event:
                self._loop.call_soon_threadsafe(self._stop_event.set)
            # Give it 1s to shut down, then stop the loop
            import time as _time
            _time.sleep(0.5)
            self._loop.call_soon_threadsafe(self._loop.stop)
