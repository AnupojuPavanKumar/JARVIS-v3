# skills/system_report_skill.py — JARVIS SYSTEM REPORT SKILL
# Full live hardware snapshot: CPU, RAM, VRAM, disk, battery, network, processes.
# Activated by "system report", "full status", "how is the system" etc.

SKILL_NAME  = "system_report"
TRIGGERS    = ["system report", "full status", "full system status", "hardware report",
                "how is the system", "how is my pc", "pc health", "health check",
                "system health", "resource usage"]
DESCRIPTION = "Speaks a full live system health report including CPU, RAM, VRAM, disk, battery."


def run(command: str, context: dict) -> str:
    import psutil, datetime

    lines = []

    # CPU
    cpu    = psutil.cpu_percent(interval=0.5)
    cores  = psutil.cpu_count(logical=False)
    freq   = psutil.cpu_freq()
    freq_s = f" @ {freq.current:.0f}MHz" if freq else ""
    lines.append(f"CPU: {cpu:.0f}% load ({cores} cores{freq_s})")

    # RAM
    ram = psutil.virtual_memory()
    lines.append(
        f"RAM: {ram.percent:.0f}% used "
        f"({ram.used//1024//1024//1024:.1f}GB / {ram.total//1024//1024//1024:.1f}GB)"
    )

    # Disk
    disk = psutil.disk_usage("/")
    lines.append(
        f"Disk C: {disk.percent:.0f}% used "
        f"({disk.free//1024//1024//1024:.0f}GB free of {disk.total//1024//1024//1024:.0f}GB)"
    )

    # Battery
    bat = psutil.sensors_battery()
    if bat:
        status = "charging" if bat.power_plugged else "on battery"
        mins   = int(bat.secsleft / 60) if bat.secsleft > 0 and not bat.power_plugged else 0
        time_s = f", {mins}min remaining" if mins > 0 else ""
        lines.append(f"Battery: {bat.percent:.0f}% ({status}{time_s})")

    # VRAM (NVIDIA)
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            used, total = result.stdout.strip().split(", ")
            pct = int(used) * 100 // int(total)
            lines.append(f"VRAM: {pct}% used ({used}MB / {total}MB)")
    except Exception:
        pass

    # Network
    try:
        net = psutil.net_io_counters()
        lines.append(
            f"Network: sent {net.bytes_sent//1024//1024}MB, "
            f"recv {net.bytes_recv//1024//1024}MB this session"
        )
    except Exception:
        pass

    # Uptime
    secs   = int(datetime.datetime.now().timestamp() - psutil.boot_time())
    h, rem = divmod(secs, 3600)
    m      = rem // 60
    lines.append(f"Uptime: {h}h {m}m")

    # Top 3 CPU consumers
    try:
        procs = sorted(
            psutil.process_iter(["name", "cpu_percent"]),
            key=lambda p: p.info.get("cpu_percent") or 0,
            reverse=True
        )[:3]
        names = [p.info["name"] for p in procs if p.info.get("name")]
        if names:
            lines.append(f"Top processes: {', '.join(names)}")
    except Exception:
        pass

    summary  = " | ".join(lines)
    alert    = ""
    if cpu > 85:
        alert += " Warning: CPU is under heavy load."
    if ram.percent > 85:
        alert += " Warning: RAM is nearly full."

    return f"System report, sir: {summary}.{alert}"
