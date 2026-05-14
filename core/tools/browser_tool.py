# core/tools/browser_tool.py  —  JARVIS BROWSER TOOL
# Opens URLs and performs web searches via the default browser

import webbrowser
import urllib.parse


class BrowserTool:

    def search(self, query: str) -> str:
        """Open a Google search for the given query."""
        if not query.strip():
            return "No search query provided."
        try:
            encoded = urllib.parse.quote(query.strip())
            url = f"https://www.google.com/search?q={encoded}"
            webbrowser.open(url)
            return f"Opened Google search for: '{query}'"
        except Exception as e:
            return f"Search error: {e}"

    def open_url(self, url: str) -> str:
        """Open a specific URL in the default browser."""
        if not url.strip():
            return "No URL provided."
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return f"Opened: {url}"
        except Exception as e:
            return f"URL open error: {e}"
