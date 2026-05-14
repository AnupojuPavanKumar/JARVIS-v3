# core/web_research.py  —  JARVIS WEB RESEARCH AGENT
# ──────────────────────────────────────────────────────────────────────────────
# Gives JARVIS the ability to READ web pages, not just open them.
#
# Pipeline:
#   1. DuckDuckGo search (no API key needed)
#   2. Fetch top result HTML with requests
#   3. Strip to clean text with BeautifulSoup
#   4. Summarise with Ollama (mistral/llama3/phi3 depending on length)
#   5. Speak response back
#
# Commands:
#   "research <topic>"
#   "what is <topic>"   (triggers research if Ollama is offline)
#   "latest news on <topic>"
#   "read <url>"
#
# Dependencies: requests (installed), beautifulsoup4 (pip install beautifulsoup4)
# ──────────────────────────────────────────────────────────────────────────────

import re
import html
import urllib.parse
import requests
from typing import Optional

OLLAMA_URL = "http://localhost:11434/api/generate"

# ──────────────────────────────────────────────────────────────────────────────
# HTML CLEANER
# ──────────────────────────────────────────────────────────────────────────────

def _strip_html(raw_html: str, max_chars: int = 8000) -> str:
    """
    Strip HTML to clean plain text using BeautifulSoup (best) or
    a regex fallback if bs4 is not installed.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "header", "footer",
                          "aside", "form", "noscript", "iframe", "img",
                          "svg", "button", "input", "meta", "link"]):
            tag.decompose()

        # Prefer article / main body content
        body = (soup.find("article")
                or soup.find("main")
                or soup.find(id="mw-content-text")  # Wikipedia
                or soup.find(class_="article-body")
                or soup.body)

        text = body.get_text(separator="\n") if body else soup.get_text("\n")
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
        return "\n".join(lines)[:max_chars]

    except ImportError:
        # Regex fallback — less accurate but works without bs4
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
        return "\n".join(lines)[:max_chars]


# ──────────────────────────────────────────────────────────────────────────────
# SEARCH  (3-layer: DDG Instant API → Bing HTML → Wikipedia API)
# No API keys needed. Automatically falls back if one source fails.
# ──────────────────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── Layer 1: DuckDuckGo Instant Answer API ────────────────────────────────────
def _ddg_instant(query: str) -> Optional[str]:
    """
    DDG Instant Answer API — returns a text abstract directly (no scraping).
    No API key, no rate limit for reasonable usage.
    """
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1",
                    "skip_disambig": "1", "no_redirect": "1"},
            timeout=8,
        )
        data = r.json()
        abstract = data.get("AbstractText", "").strip()
        if abstract and len(abstract) > 50:
            return abstract
        # Try RelatedTopics snippets
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict):
                text = topic.get("Text", "")
                if len(text) > 50:
                    return text
        return None
    except Exception as e:
        print(f"[WebResearch] DDG Instant API error: {e}")
        return None


# ── Layer 2: Bing HTML scrape ─────────────────────────────────────────────────
def _bing_top_urls(query: str, n: int = 3) -> list[str]:
    """Scrape top result URLs from Bing's HTML search page."""
    try:
        url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}&count=5"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        # Bing result links are in <a> tags inside <li class="b_algo">
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            urls = []
            for li in soup.find_all("li", class_="b_algo")[:n]:
                a = li.find("a", href=True)
                if a and a["href"].startswith("http"):
                    urls.append(a["href"])
            return urls[:n]
        except ImportError:
            # Regex fallback
            raw = re.findall(r'<a[^>]+href="(https?://[^"]+)"', r.text)
            clean = [u for u in raw if "bing.com" not in u and "microsoft.com" not in u]
            return clean[:n]
    except Exception as e:
        print(f"[WebResearch] Bing search error: {e}")
        return []


# ── Layer 3: Wikipedia search API ────────────────────────────────────────────
_WIKI_HEADERS = {
    "User-Agent": "JARVIS-AI-Assistant/2.0 (personal project; contact: jarvis@localhost)",
    "Accept": "application/json",
}

def _wikipedia_summary(query: str) -> Optional[str]:
    """
    Use Wikipedia's public REST API to get a clean article summary.
    Free, no auth, reliable for factual queries.
    """
    try:
        # Step 1: search for matching article
        search_r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": "1"},
            headers=_WIKI_HEADERS,
            timeout=8,
        )
        results = search_r.json().get("query", {}).get("search", [])
        if not results:
            return None
        title = results[0]["title"]

        # Step 2: get the summary extract
        summary_r = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}",
            headers=_WIKI_HEADERS,
            timeout=8,
        )
        data = summary_r.json()
        extract = data.get("extract", "").strip()
        if extract and len(extract) > 100:
            return f"According to Wikipedia: {extract[:600]}"
        return None
    except Exception as e:
        print(f"[WebResearch] Wikipedia API error: {e}")
        return None


# ── Combined smart search ─────────────────────────────────────────────────────
def _ddg_top_urls(query: str, n: int = 3) -> list[str]:
    """Return top-n result URLs — tries Bing after DDG HTML (kept for compat)."""
    urls = _bing_top_urls(query, n)
    return urls


def _fetch_page(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch a URL and return stripped plain text, or None on failure."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "text/html" not in ct and "text/" not in ct:
            return None
        return _strip_html(r.text)
    except Exception as e:
        print(f"[WebResearch] Fetch error ({url}): {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# OLLAMA SUMMARIZER
# ──────────────────────────────────────────────────────────────────────────────

def _summarise(text: str, query: str, model: str = "qwen2.5-coder:7b") -> Optional[str]:
    """Send scraped text to Ollama for summarization."""
    prompt = (
        f"You are JARVIS, an AI assistant. Based on the following web page content, "
        f"answer this question concisely: {query}\n\n"
        f"--- WEB CONTENT ---\n{text[:5000]}\n--- END ---\n\n"
        f"Give a clear, spoken-style answer in 3-5 sentences. "
        f"Do not say 'based on the content' — just answer directly."
    )
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,  # Increased timeout for local VRAM pressure
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        print(f"[WebResearch] Summarise error: {e}")
        return None


def _best_model() -> str:
    """Pick the model that is ALREADY loaded to avoid VRAM thrashing."""
    try:
        r = requests.get("http://localhost:11434/api/ps", timeout=2)
        if r.status_code == 200:
            models = r.json().get("models", [])
            if models:
                return models[0]["name"]  # Use whatever is currently in VRAM
    except Exception:
        pass
    return "qwen2.5-coder:7b"


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

class WebResearchAgent:
    """
    JARVIS's web research capability.
    Searches the web, reads pages, and answers questions — all locally.
    """

    def research(self, query: str) -> str:
        """
        Full pipeline: RealTime API (Fastest) → DDG Instant → Bing fetch → Wikipedia → spoken answer.
        E.g.: "research latest news on SpaceX"
        """
        print(f"[WebResearch] Researching: {query}")

        # ── Layer 0: Real-Time Data (Weather/Crypto) ─────────────────────
        try:
            from core.tools.realtime_tool import RealTimeTool
            rt = RealTimeTool()
            res = rt.run_query(query)
            if res:
                print(f"[WebResearch] Real-time data found")
                return res
        except Exception:
            pass

        # ── Layer 1: DDG Instant Answer (fastest, no page fetch needed) ──
        instant = _ddg_instant(query)
        if instant:
            print(f"[WebResearch] DDG instant answer found")
            model   = _best_model()
            summary = _summarise(instant, query, model)
            return summary or instant

        # ── Layer 2: Bing search → fetch page ────────────────────────────
        urls = _bing_top_urls(query, n=3)
        if urls:
            content = None
            used_url = None
            for url in urls:
                print(f"[WebResearch] Fetching: {url}")
                text = _fetch_page(url)
                if text and len(text) > 200:
                    content = text
                    used_url = url
                    break

            if content:
                model   = _best_model()
                summary = _summarise(content, query, model)
                if summary:
                    return summary
                preview = content[:300].replace("\n", " ")
                return (f"Ollama is offline, sir. Here's what I found: {preview}... "
                        f"Source: {used_url}")

        # ── Layer 3: Wikipedia REST API ───────────────────────────────────
        print(f"[WebResearch] Trying Wikipedia for: {query}")
        wiki = _wikipedia_summary(query)
        if wiki:
            model   = _best_model()
            summary = _summarise(wiki, query, model)
            return summary or wiki

        return ("I couldn't find reliable information on that topic, sir. "
                "Please check your internet connection.")

    def read_url(self, url: str, question: str = "summarise this page") -> str:
        """
        Read a specific URL and answer a question about it.
        E.g.: "read https://example.com and summarise it"
        """
        print(f"[WebResearch] Reading URL: {url}")
        text = _fetch_page(url)
        if not text:
            return f"I couldn't read that page, sir. It may require a login or be unavailable."
        model   = _best_model()
        summary = _summarise(text, question, model)
        return summary or f"Page content (first 300 chars): {text[:300]}"

    def quick_answer(self, query: str) -> str:
        """
        Faster variant: just search and return the first result snippet
        without a full Ollama summarise. Good for simple factual lookups.
        """
        urls = _ddg_top_urls(query, n=1)
        if not urls:
            return "No internet connection, sir."
        text = _fetch_page(urls[0])
        if not text:
            return f"Couldn't read the page, sir. Try: {urls[0]}"
        # First meaningful paragraph
        paras = [p for p in text.split("\n") if len(p) > 80][:3]
        return " ".join(paras)[:400] if paras else text[:300]


# ── Singleton ────────────────────────────────────────────────────────────────
_agent: Optional[WebResearchAgent] = None

def get_web_agent() -> WebResearchAgent:
    global _agent
    if _agent is None:
        _agent = WebResearchAgent()
    return _agent


# ──────────────────────────────────────────────────────────────────────────────
# URL EXTRACTOR (helper for command_engine)
# ──────────────────────────────────────────────────────────────────────────────

def extract_url(text: str) -> Optional[str]:
    """Pull a URL out of a command string."""
    m = re.search(r'https?://\S+', text)
    return m.group(0) if m else None


def extract_research_query(text: str) -> str:
    """Strip command prefixes to get the research query."""
    text = re.sub(
        r"^(research|look up|look up|find out about|what is|tell me about|"
        r"latest news on|news about|search for|google)\s+",
        "", text.lower()
    ).strip()
    return text
