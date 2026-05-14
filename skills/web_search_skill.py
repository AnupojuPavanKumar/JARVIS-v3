import webbrowser
import urllib.parse
import re

SKILL_NAME = "Web Search Skill"
DESCRIPTION = "Performs searches on Google, YouTube, and Wikipedia. Can also conduct deep autonomous research."
TRIGGERS = ["search", "google", "find", "look up", "lookup", "youtube", "wikipedia", "what is", "who is", "research", "tell me about"]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()
    
    # Check for deep research intent
    research_agent = context.get("research_agent")
    if research_agent and any(word in cmd for word in ["research", "tell me about", "what is", "who is"]):
        # Heuristic: if command is long and doesn't specify 'on google/youtube', it's research
        if len(cmd.split()) > 4 and not any(w in cmd for w in ["youtube", "wikipedia", "on google"]):
            q = (cmd.replace("research","").replace("tell me about","")
                    .replace("what is","").replace("who is","").strip())
            if q:
                return research_agent.research(q)

    if "youtube" in cmd:
        return _youtube(cmd)
    if "wikipedia" in cmd:
        return _wikipedia(cmd)
    if any(w in cmd.split() for w in ("search","google","find","look up","lookup")):
        return _search(cmd)
        
    return None

def _search(cmd):
    q = (cmd.replace("search google for","").replace("search for","")
            .replace("google","").replace("search","")
            .replace("find","").replace("look up","").replace("lookup","")
            .strip())
    if not q: return "What should I search for, sir?"
    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(q)}")
    return f"Searching Google for '{q}', sir."

def _youtube(cmd):
    q = (cmd.replace("search youtube for","").replace("play on youtube","")
            .replace("youtube search","").replace("youtube","")
            .replace("search","").replace("play","").replace("watch","").strip())
    if not q:
        webbrowser.open("https://youtube.com")
        return "Opening YouTube, sir."
    webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}")
    return f"Searching YouTube for '{q}', sir."

def _wikipedia(cmd):
    q = (cmd.replace("wikipedia","").replace("what is","")
            .replace("who is","").replace("tell me about","").strip())
    if not q: return "What would you like to know, sir?"
    webbrowser.open(f"https://en.wikipedia.org/wiki/Special:Search?search={urllib.parse.quote(q)}")
    return f"Opening Wikipedia for '{q}', sir."
