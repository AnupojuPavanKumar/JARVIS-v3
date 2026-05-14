# skills/weather_skill.py — JARVIS WEATHER SKILL v2
# Fetches live weather using wttr.in (no API key needed).
# Drop-in skill: auto-detected by PluginManager on startup.
#
# FIX v2:
#   - Removed webbrowser.open fallback that was opening bad URLs
#     (e.g. wttr.in/how%20is%20today when city extraction failed)
#   - Added city allowlist guard — only opens wttr.in for real city names
#   - Natural command parsing now whitelists only known city-like tokens
#   - Defaults to configured HOME_CITY (Hyderabad) for bare "weather" queries

SKILL_NAME  = "weather"
TRIGGERS    = ["weather", "temperature", "forecast", "how hot", "how cold",
                "will it rain", "whats the weather", "what's the weather",
                "weather today", "weather now", "weather report"]
DESCRIPTION = "Gets live weather for your city using wttr.in (no API key)"

HOME_CITY   = "Hyderabad"    # ← change this to your city if needed


def run(command: str, context: dict) -> str:
    import re
    import requests

    # ── Extract city only when explicitly specified ──────────────────────────
    # Pattern: "weather in <city>", "weather for <city>", "forecast for <city>"
    city_match = re.search(
        r'(?:weather in|weather for|temperature in|forecast for|weather at)\s+([a-zA-Z\s]{2,30}?)(?:\s+today|\s+now|\s+please|$)',
        command.lower()
    )

    if city_match:
        extracted = city_match.group(1).strip()
        # Guard: must look like a real city (only letters and spaces, reasonable length)
        if 2 <= len(extracted) <= 30 and re.match(r'^[a-zA-Z\s]+$', extracted):
            city = extracted.replace(" ", "+")
        else:
            city = context.get("home_city", HOME_CITY)
    else:
        # No city mentioned → use home city
        city = context.get("home_city", HOME_CITY)

    city_display = city.replace("+", " ").title()

    try:
        url = f"https://wttr.in/{city}?format=j1"
        r   = requests.get(url, timeout=6, headers={"User-Agent": "JARVIS/3.0"})

        if r.status_code == 404 or "location not found" in r.text.lower():
            # City not recognised → fall back to home city
            city         = HOME_CITY
            city_display = city
            r = requests.get(
                f"https://wttr.in/{city}?format=j1",
                timeout=6,
                headers={"User-Agent": "JARVIS/3.0"}
            )

        r.raise_for_status()
        data = r.json()

        current  = data["current_condition"][0]
        temp_c   = current["temp_C"]
        feels    = current["FeelsLikeC"]
        desc     = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind_kph = current["windspeedKmph"]

        return (
            f"Weather in {city_display}: {desc}. "
            f"{temp_c}°C, feels like {feels}°C. "
            f"Humidity {humidity}%, wind {wind_kph} km/h, sir."
        )

    except requests.exceptions.ConnectionError:
        return (
            f"I cannot reach the weather service right now, sir. "
            f"Check your internet connection."
        )
    except Exception as e:
        # NO webbrowser.open — that caused the bad URL bug
        return (
            f"Weather service returned an error for {city_display}, sir. "
            f"Try 'weather in Hyderabad' for an explicit city name."
        )
