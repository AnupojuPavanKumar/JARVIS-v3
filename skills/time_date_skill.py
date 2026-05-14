import re
import datetime

SKILL_NAME = "Time & Date Skill"
DESCRIPTION = "Handles requests for the current time and date."
TRIGGERS = ["time", "date"]

def run(command: str, context: dict) -> str:
    cmd = command.lower()
    
    if any(p in cmd for p in ("what time", "current time", "tell me the time", "what's the time", "whats the time")):
        return _time()
    
    if any(p in cmd for p in ("what date", "today's date", "what day", "todays date", "current date")):
        return _date()

    return "I can provide the time or date, sir."

def _time() -> str:
    return f"It is {datetime.datetime.now().strftime('%I:%M %p')}, sir."

def _date() -> str:
    n = datetime.datetime.now()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"Today is {days[n.weekday()]}, {n.day} {months[n.month-1]} {n.year}."
