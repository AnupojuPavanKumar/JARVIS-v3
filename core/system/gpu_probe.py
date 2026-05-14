"""
core/system/gpu_probe.py — Unified GPU Telemetry
=================================================
Fix 3: standardizes GPU VRAM queries across the entire codebase.

PROBLEM:
  HardwareSentinel used `nvidia-smi` via subprocess.
  OllamaManager used `pynvml` directly.
  These two probes can give different numbers and both crash differently
  on non-NVIDIA hardware (AMD, Intel iGPU, headless servers, Mac).

SOLUTION — Single probe with cascading fallbacks:
  1. pynvml (preferred) — zero-overhead C bindings, most accurate
  2. nvidia-smi subprocess — works even when pynvml not installed
  3. None — silent on AMD/Intel/Mac (never spams logs)

USAGE:
  from core.system.gpu_probe import get_gpu_stats
  stats = get_gpu_stats()
  # stats = {"util_pct": 42.0, "used_mb": 2048, "total_mb": 6144,
  #          "used_pct": 33.3, "source": "pynvml"} | None
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional

log = logging.getLogger("GPUProbe")

# One-shot warning flags so we don't spam logs on every poll cycle
_pynvml_warned  = False
_smi_warned     = False


def get_gpu_stats() -> Optional[dict]:
    """
    Return GPU VRAM stats as a dict, or None if no NVIDIA GPU is available.

    Dict keys:
      util_pct  — GPU core utilisation 0-100 (float)
      used_mb   — VRAM used in MB (float)
      total_mb  — VRAM total in MB (float)
      used_pct  — VRAM used percentage 0-100 (float)
      source    — "pynvml" | "nvidia-smi"
    """
    result = _probe_pynvml()
    if result is not None:
        return result
    return _probe_nvidia_smi()


def get_vram_used_pct() -> Optional[float]:
    """Convenience: return VRAM used % (0-100) or None."""
    stats = get_gpu_stats()
    return stats["used_pct"] if stats else None


# ── Probe 1: pynvml (best — C bindings, zero subprocess overhead) ─────────────

def _probe_pynvml() -> Optional[dict]:
    global _pynvml_warned
    try:
        from pynvml import (nvmlInit, nvmlDeviceGetHandleByIndex,
                            nvmlDeviceGetMemoryInfo, nvmlDeviceGetUtilizationRates)
        nvmlInit()
        handle   = nvmlDeviceGetHandleByIndex(0)
        mem      = nvmlDeviceGetMemoryInfo(handle)
        util     = nvmlDeviceGetUtilizationRates(handle)
        used_mb  = mem.used  / 1024 / 1024
        total_mb = mem.total / 1024 / 1024
        return {
            "util_pct": float(util.gpu),
            "used_mb":  round(used_mb,  1),
            "total_mb": round(total_mb, 1),
            "used_pct": round(100 * mem.used / mem.total, 1) if mem.total else 0.0,
            "source":   "pynvml",
        }
    except ImportError:
        if not _pynvml_warned:
            log.debug("[GPUProbe] pynvml not installed — falling back to nvidia-smi.")
            _pynvml_warned = True
    except Exception as exc:
        if not _pynvml_warned:
            log.debug(f"[GPUProbe] pynvml failed: {exc} — falling back to nvidia-smi.")
            _pynvml_warned = True
    return None


# ── Probe 2: nvidia-smi subprocess (works without pynvml) ─────────────────────

def _probe_nvidia_smi() -> Optional[dict]:
    global _smi_warned
    try:
        res = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,nounits,noheader"],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode != 0:
            return None
        parts = res.stdout.strip().split(",")
        if len(parts) < 3:
            return None
        util  = float(parts[0].strip())
        used  = float(parts[1].strip())
        total = float(parts[2].strip())
        return {
            "util_pct": util,
            "used_mb":  used,
            "total_mb": total,
            "used_pct": round(100 * used / total, 1) if total else 0.0,
            "source":   "nvidia-smi",
        }
    except FileNotFoundError:
        # nvidia-smi not in PATH — AMD/Intel/Mac — silent
        return None
    except Exception as exc:
        if not _smi_warned:
            log.debug(f"[GPUProbe] nvidia-smi failed: {exc}")
            _smi_warned = True
        return None
