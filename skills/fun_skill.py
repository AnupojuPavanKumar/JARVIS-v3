import random

SKILL_NAME = "Fun & Games"
DESCRIPTION = "Provides jokes, coin flips, and dice rolls."
TRIGGERS = ["joke", "flip a coin", "coin flip", "roll a dice", "roll dice", "roll a die"]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()
    
    if "joke" in cmd:
        return _joke()
    if "flip a coin" in cmd or "coin flip" in cmd:
        return f"{'Heads' if random.random()>.5 else 'Tails'}, sir."
    if "roll" in cmd and ("dice" in cmd or "die" in cmd):
        return f"The dice shows {random.randint(1,6)}, sir."
        
    return None

def _joke():
    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "I told my AI to find me a date. It returned None.",
        "Why was the computer cold? It left its Windows open.",
        "There are 10 types of people: those who understand binary and those who don't.",
        "I would make a joke about UDP, but you might not get it.",
        "A SQL query walks into a bar and asks two tables: can I join you?",
        "Why do Java developers wear glasses? Because they don't C#.",
        "I have a joke about recursion, but first I need to tell you a joke about recursion.",
    ]
    return random.choice(jokes)
