import subprocess

SKILL_NAME = "Automation Modes"
DESCRIPTION = "Activates predefined workstation modes (Coding, Study, Gaming, Work, Focus)."
TRIGGERS = ["coding mode", "study mode", "gaming mode", "good night", "work mode", "focus mode"]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()
    
    if "coding mode" in cmd:
        return _start_coding_mode()
    if "study mode" in cmd:
        return _start_study_mode()
    if "gaming mode" in cmd:
        return _start_gaming_mode()
    if "good night" in cmd:
        return _good_night()
    if "work mode" in cmd:
        return _work_mode()
    if "focus mode" in cmd:
        return _focus_mode()
        
    return None

def _start_coding_mode():
    subprocess.Popen(["code"], shell=True)
    subprocess.Popen(["cmd", "/c", "start", "https://github.com"], shell=True)
    return "Coding mode activated. Happy developing, sir."

def _start_study_mode():
    subprocess.Popen(["cmd", "/c", "start", "https://notion.so"], shell=True)
    return "Study mode activated. Focus well, sir."

def _start_gaming_mode():
    subprocess.Popen(["cmd", "/c", "start", "steam://open/main"], shell=True)
    return "Gaming mode activated. Have fun, sir."

def _good_night():
    # Close distractions
    for app in ["chrome.exe", "discord.exe", "spotify.exe"]:
        subprocess.run(["taskkill", "/im", app, "/f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Good night, sir. Rest well."

def _work_mode():
    subprocess.Popen(["code"], shell=True)
    subprocess.Popen(["cmd", "/c", "start", "https://gmail.com"], shell=True)
    return "Work mode activated. VS Code and Gmail opened, sir."

def _focus_mode():
    for app in ["discord.exe", "spotify.exe", "steam.exe"]:
        subprocess.run(["taskkill", "/im", app, "/f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Focus mode activated. Distractions closed, sir."
