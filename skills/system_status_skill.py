import psutil
import datetime

SKILL_NAME = "System Status Skill"
DESCRIPTION = "Provides hardware statistics and system health information."
TRIGGERS = [
    "system status", "system info", "how is my system", "pc status", "system report",
    "cpu usage", "processor", "cpu load",
    "ram usage", "memory usage", "ram load",
    "battery", "charge level", "battery level",
    "disk", "storage", "hard drive", "free space",
    "network", "internet", "ip address", "wifi",
    "uptime", "how long", "running for",
    "top process", "running apps", "what's running",
    "temperature", "cpu temp"
]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()

    if any(p in cmd for p in ("system status","system info","how is my system","pc status","system report")):
        return _system_full()
    if any(p in cmd for p in ("cpu usage","processor","cpu load")):
        return f"CPU is at {psutil.cpu_percent(interval=0.5):.0f}%, sir."
    if any(p in cmd for p in ("ram usage","memory usage","ram load")):
        r = psutil.virtual_memory()
        return f"RAM is {r.percent:.0f}% used, {r.used//1024//1024} MB of {r.total//1024//1024} MB."
    if any(p in cmd for p in ("battery","charge level","battery level")):
        return _battery()
    if any(p in cmd for p in ("disk","storage","hard drive","free space")):
        return _disk()
    if any(p in cmd for p in ("network","internet","ip address","wifi")):
        return _network()
    if any(p in cmd for p in ("uptime","how long","running for")):
        return _uptime()
    if any(p in cmd for p in ("top process","running apps","what's running")):
        return _top_processes()
    if any(p in cmd for p in ("temperature","cpu temp")):
        return _cpu_temp()
        
    return None # Shouldn't hit this if TRIGGERS are accurate

def _system_full():
    cpu  = psutil.cpu_percent(interval=0.5)
    ram  = psutil.virtual_memory()
    bat  = psutil.sensors_battery()
    disk = psutil.disk_usage('/')
    bp   = f"{bat.percent:.0f}%" if bat else "N/A"
    return (f"CPU {cpu:.0f}%, RAM {ram.percent:.0f}% "
            f"({ram.used//1024//1024} MB used), "
            f"Disk {disk.percent:.0f}% used, Battery {bp}.")

def _battery():
    b = psutil.sensors_battery()
    if not b: return "Battery info unavailable, sir."
    status = "charging" if b.power_plugged else "discharging"
    mins = int(b.secsleft/60) if b.secsleft>0 and not b.power_plugged else 0
    time_s = f", {mins} minutes remaining" if mins > 0 else ""
    return f"Battery is {b.percent:.0f}%, {status}{time_s}, sir."

def _disk():
    d = psutil.disk_usage('/')
    free  = d.free  //1024//1024//1024
    total = d.total //1024//1024//1024
    return f"Disk is {d.percent:.0f}% used. {free} GB free of {total} GB total, sir."

def _network():
    try:
        import socket
        ip  = socket.gethostbyname(socket.gethostname())
        net = psutil.net_io_counters()
        return (f"Local IP: {ip}. "
                f"Sent {net.bytes_sent//1024//1024} MB, "
                f"received {net.bytes_recv//1024//1024} MB this session.")
    except Exception:
        return "Network info unavailable, sir."

def _uptime():
    secs = int(datetime.datetime.now().timestamp() - psutil.boot_time())
    return f"System running for {secs//3600}h {(secs%3600)//60}m, sir."

def _top_processes():
    procs = sorted(psutil.process_iter(['name','cpu_percent']),
                   key=lambda p: p.info['cpu_percent'] or 0,
                   reverse=True)[:5]
    names = [p.info['name'] for p in procs if p.info.get('name')]
    return f"Top processes: {', '.join(names)}, sir."

def _cpu_temp():
    try:
        t = psutil.sensors_temperatures()
        for name, entries in (t or {}).items():
            if entries:
                return f"CPU temperature is {entries[0].current:.0f}°C, sir."
    except Exception:
        pass
    return "Temperature sensors unavailable on this system, sir."
