from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urljoin
import re
import subprocess
import sys
import time

import requests


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class _HTMLSnapshotParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self.links: list[dict[str, str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag == "a":
            attrs_map = dict(attrs)
            href = attrs_map.get("href")
            if href:
                self.links.append({"href": href, "text": ""})

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        self.text_parts.append(text)
        if self.links:
            last = self.links[-1]
            if not last["text"]:
                last["text"] = text[:140]


@dataclass
class BrowserSnapshot:
    url: str
    final_url: str
    title: str
    engine: str
    text_excerpt: str
    links: list[dict[str, str]] = field(default_factory=list)
    status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "engine": self.engine,
            "text_excerpt": self.text_excerpt,
            "links": self.links,
            "status_code": self.status_code,
        }


@dataclass
class BrowserWorkflowTrace:
    start_url: str
    engine: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_url": self.start_url,
            "engine": self.engine,
            "steps": self.steps,
        }


@dataclass
class BrowserAction:
    kind: str
    target: str = ""
    value: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "target": self.target,
            "value": self.value,
        }


class BrowserAutomation:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    @staticmethod
    def extract_first_url(text: str) -> str | None:
        match = re.search(r"https?://[^\s)]+", text)
        return match.group(0) if match else None

    @staticmethod
    def playwright_available() -> bool:
        with suppress(Exception):
            import importlib.util

            return bool(importlib.util.find_spec("playwright"))
        return False

    def capture_page(self, url: str) -> BrowserSnapshot:
        if self.playwright_available():
            with suppress(Exception):
                return self._capture_with_playwright(url)
        return self._capture_with_requests(url)

    def parse_workflow_instructions(self, prompt: str) -> tuple[str | None, list[BrowserAction]]:
        url = self.extract_first_url(prompt)
        lowered = prompt.lower()
        actions: list[BrowserAction] = []

        for clause in self._split_workflow_clauses(prompt):
            clause_lower = clause.lower()
            if clause_lower.startswith(("follow ", "open link ", "navigate to ")):
                cleaned = self._strip_action_prefix(
                    clause,
                    ("follow ", "open link ", "navigate to "),
                )
                if cleaned and not cleaned.lower().startswith("http"):
                    actions.append(BrowserAction(kind="follow", target=cleaned))
                continue

            if clause_lower.startswith("click "):
                cleaned = self._strip_action_prefix(clause, ("click ",))
                if cleaned:
                    actions.append(BrowserAction(kind="click", target=cleaned))
                continue

            fill_match = re.match(r"fill\s+(.+?)\s+with\s+(.+)$", clause, flags=re.IGNORECASE)
            if fill_match:
                actions.append(
                    BrowserAction(
                        kind="fill",
                        target=fill_match.group(1).strip(" .!?"),
                        value=fill_match.group(2).strip(" .!?"),
                    )
                )
                continue

            type_match = re.match(r"type\s+(.+?)\s+into\s+(.+)$", clause, flags=re.IGNORECASE)
            if type_match:
                actions.append(
                    BrowserAction(
                        kind="fill",
                        target=type_match.group(2).strip(" .!?"),
                        value=type_match.group(1).strip(" .!?"),
                    )
                )
                continue

            search_match = re.match(r"search\s+for\s+(.+)$", clause, flags=re.IGNORECASE)
            if search_match:
                actions.append(BrowserAction(kind="fill", target="search", value=search_match.group(1).strip(" .!?")))
                actions.append(BrowserAction(kind="submit", target="search"))
                continue

            if clause_lower in {"submit", "submit form", "press enter", "search"}:
                actions.append(BrowserAction(kind="submit", target=clause.strip(" .!?")))

        return url, actions

    def run_workflow(self, url: str, actions: list[BrowserAction]) -> BrowserWorkflowTrace:
        if self.playwright_available():
            with suppress(Exception):
                return self._run_workflow_with_playwright(url, actions)
        return self._run_workflow_with_requests(url, actions)

    def wikipedia_research(self, topic: str) -> dict[str, Any]:
        search_url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=opensearch&search={quote_plus(topic)}&limit=3&namespace=0&format=json"
        )
        response = self.session.get(search_url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        titles = payload[1] if len(payload) > 1 else []
        urls = payload[3] if len(payload) > 3 else []

        pages = []
        for title, url in list(zip(titles, urls))[:3]:
            summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"
            summary_response = self.session.get(summary_url, timeout=self.timeout)
            summary_response.raise_for_status()
            summary_payload = summary_response.json()
            pages.append(
                {
                    "title": title,
                    "url": url,
                    "summary": summary_payload.get("extract", ""),
                }
            )

        return {
            "topic": topic,
            "pages": pages,
            "engine": "wikipedia",
        }

    def _capture_with_requests(self, url: str) -> BrowserSnapshot:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        parser = _HTMLSnapshotParser()
        parser.feed(response.text)
        excerpt = " ".join(parser.text_parts[:40])[:500]
        normalized_links = []
        for item in parser.links[:8]:
            normalized_links.append(
                {
                    "href": urljoin(response.url, item["href"]),
                    "text": item["text"],
                }
            )

        return BrowserSnapshot(
            url=url,
            final_url=response.url,
            title=parser.title or response.url,
            engine="requests",
            text_excerpt=excerpt,
            links=normalized_links,
            status_code=response.status_code,
        )

    def _capture_with_playwright(self, url: str) -> BrowserSnapshot:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            title = page.title()
            final_url = page.url
            excerpt = page.locator("body").inner_text(timeout=self.timeout * 1000)[:500]
            links = []
            for handle in page.locator("a").element_handles()[:8]:
                href = handle.get_attribute("href") or ""
                text = (handle.inner_text() or "")[:140]
                if href:
                    links.append({"href": urljoin(final_url, href), "text": text})
            browser.close()

        return BrowserSnapshot(
            url=url,
            final_url=final_url,
            title=title or final_url,
            engine="playwright",
            text_excerpt=excerpt,
            links=links,
            status_code=200,
        )

    def _run_workflow_with_requests(self, url: str, actions: list[BrowserAction]) -> BrowserWorkflowTrace:
        current = self._capture_with_requests(url)
        trace = BrowserWorkflowTrace(start_url=url, engine="requests")
        trace.steps.append(
            {
                "action": "open",
                "target": url,
                "snapshot": current.to_dict(),
            }
        )

        for action in actions:
            if action.kind == "click":
                match = next(
                    (
                        link
                        for link in current.links
                        if action.target.lower() in (link.get("text", "") + " " + link.get("href", "")).lower()
                    ),
                    None,
                )
                if match is None:
                    trace.steps.append(
                        {
                            "action": action.kind,
                            "target": action.target,
                            "error": f"The lightweight browser engine could not find a clickable target for '{action.target}'.",
                        }
                    )
                    break

                current = self._capture_with_requests(match["href"])
                trace.steps.append(
                    {
                        "action": action.kind,
                        "target": action.target,
                        "snapshot": current.to_dict(),
                    }
                )
                continue

            if action.kind != "follow":
                trace.steps.append(
                    {
                        "action": action.kind,
                        "target": action.target,
                        "value": action.value,
                        "error": f"The lightweight browser engine cannot execute '{action.kind}' actions.",
                    }
                )
                continue

            match = next(
                (
                    link
                    for link in current.links
                    if action.target.lower() in (link.get("text", "") + " " + link.get("href", "")).lower()
                ),
                None,
            )
            if match is None:
                trace.steps.append(
                    {
                        "action": action.kind,
                        "target": action.target,
                        "error": f"No matching link found for '{action.target}'.",
                    }
                )
                break

            current = self._capture_with_requests(match["href"])
            trace.steps.append(
                {
                    "action": action.kind,
                    "target": action.target,
                    "snapshot": current.to_dict(),
                }
            )

        return trace

    def _run_workflow_with_playwright(self, url: str, actions: list[BrowserAction]) -> BrowserWorkflowTrace:
        from playwright.sync_api import sync_playwright

        trace = BrowserWorkflowTrace(start_url=url, engine="playwright")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            trace.steps.append(
                {
                    "action": "open",
                    "target": url,
                    "snapshot": self._snapshot_from_playwright_page(page, url),
                }
            )

            for action in actions:
                if action.kind == "follow":
                    locator = page.get_by_role("link", name=re.compile(re.escape(action.target), re.IGNORECASE)).first
                    if locator.count() == 0:
                        trace.steps.append(
                            {
                                "action": action.kind,
                                "target": action.target,
                                "error": f"No matching link found for '{action.target}'.",
                            }
                        )
                        break

                    locator.click(timeout=self.timeout * 1000)
                    page.wait_for_load_state("domcontentloaded", timeout=self.timeout * 1000)
                    trace.steps.append(
                        {
                            "action": action.kind,
                            "target": action.target,
                            "snapshot": self._snapshot_from_playwright_page(page, page.url),
                        }
                    )
                    continue

                if action.kind == "fill":
                    field = self._locate_field(page, action.target)
                    if field is None or field.count() == 0:
                        trace.steps.append(
                            {
                                "action": action.kind,
                                "target": action.target,
                                "value": action.value,
                                "error": f"No matching field found for '{action.target}'.",
                            }
                        )
                        break

                    field.fill(action.value, timeout=self.timeout * 1000)
                    trace.steps.append(
                        {
                            "action": action.kind,
                            "target": action.target,
                            "value": action.value,
                            "snapshot": self._snapshot_from_playwright_page(page, page.url),
                        }
                    )
                    continue

                if action.kind == "click":
                    if not self._click_target(page, action.target):
                        trace.steps.append(
                            {
                                "action": action.kind,
                                "target": action.target,
                                "error": f"No clickable target was found for '{action.target}'.",
                            }
                        )
                        break

                    page.wait_for_load_state("domcontentloaded", timeout=self.timeout * 1000)
                    trace.steps.append(
                        {
                            "action": action.kind,
                            "target": action.target,
                            "snapshot": self._snapshot_from_playwright_page(page, page.url),
                        }
                    )
                    continue

                if action.kind == "submit":
                    if not self._submit_form(page, action.target):
                        trace.steps.append(
                            {
                                "action": action.kind,
                                "target": action.target,
                                "error": "No submit control or active field was available.",
                            }
                        )
                        break

                    page.wait_for_load_state("domcontentloaded", timeout=self.timeout * 1000)
                    trace.steps.append(
                        {
                            "action": action.kind,
                            "target": action.target,
                            "snapshot": self._snapshot_from_playwright_page(page, page.url),
                        }
                    )
                    continue

            browser.close()

        return trace

    def _snapshot_from_playwright_page(self, page, original_url: str) -> dict[str, Any]:
        title = page.title()
        final_url = page.url
        excerpt = page.locator("body").inner_text(timeout=self.timeout * 1000)[:500]
        links = []
        for handle in page.locator("a").element_handles()[:8]:
            href = handle.get_attribute("href") or ""
            text = (handle.inner_text() or "")[:140]
            if href:
                links.append({"href": urljoin(final_url, href), "text": text})

        return BrowserSnapshot(
            url=original_url,
            final_url=final_url,
            title=title or final_url,
            engine="playwright",
            text_excerpt=excerpt,
            links=links,
            status_code=200,
        ).to_dict()

    def _split_workflow_clauses(self, prompt: str) -> list[str]:
        stripped = prompt.strip()
        prefix_match = re.match(r"^(browse|research|analyze|inspect|summarize)\s+https?://\S+\s*(.*)$", stripped, flags=re.IGNORECASE)
        if prefix_match and prefix_match.group(2):
            stripped = prefix_match.group(2).strip()
        elif prefix_match:
            return []

        clause_boundary = (
            r"\bthen\b|,|"
            r"\band\b(?=\s+(?:follow|click|open link|navigate to|fill|type|submit|press enter|search(?:\s+for)?)\b)"
        )
        clauses = [part.strip(" .!?") for part in re.split(clause_boundary, stripped, flags=re.IGNORECASE)]
        return [clause for clause in clauses if clause]

    def _strip_action_prefix(self, clause: str, prefixes: tuple[str, ...]) -> str:
        lowered = clause.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return clause[len(prefix):].strip(" .!?")
        return clause.strip(" .!?")

    def _locate_field(self, page, field_name: str):
        candidates = []
        name_pattern = re.compile(re.escape(field_name), re.IGNORECASE)
        with suppress(Exception):
            candidates.append(page.get_by_label(name_pattern).first)
        with suppress(Exception):
            candidates.append(page.get_by_placeholder(name_pattern).first)
        with suppress(Exception):
            candidates.append(page.get_by_role("textbox", name=name_pattern).first)
        with suppress(Exception):
            candidates.append(page.get_by_role("searchbox", name=name_pattern).first)
        with suppress(Exception):
            candidates.append(page.get_by_role("combobox", name=name_pattern).first)

        escaped = field_name.replace("\\", "\\\\").replace('"', '\\"')
        selector = (
            f'input[name*="{escaped}" i], textarea[name*="{escaped}" i], '
            f'input[placeholder*="{escaped}" i], textarea[placeholder*="{escaped}" i], '
            f'input[aria-label*="{escaped}" i], textarea[aria-label*="{escaped}" i], '
            f'input[id*="{escaped}" i], textarea[id*="{escaped}" i], '
            f'[contenteditable="true"][aria-label*="{escaped}" i]'
        )
        with suppress(Exception):
            candidates.append(page.locator(selector).first)
        with suppress(Exception):
            candidates.append(page.locator(f'input[type="{self._infer_input_type(field_name)}"]').first)

        for candidate in candidates:
            with suppress(Exception):
                if candidate and candidate.count() > 0:
                    return candidate
        with suppress(Exception):
            fallback_fields = page.locator(
                "input:not([type='hidden']):not([disabled]), textarea:not([disabled]), [contenteditable='true']"
            )
            if fallback_fields.count() > 0:
                return fallback_fields.first
        return None

    def _submit_form(self, page, target: str) -> bool:
        buttons = []
        text_targets = [target, "submit", "search", "go"]
        for label in text_targets:
            if not label:
                continue
            with suppress(Exception):
                buttons.append(page.get_by_role("button", name=re.compile(re.escape(label), re.IGNORECASE)).first)
        with suppress(Exception):
            buttons.append(page.locator("button[type='submit'], input[type='submit']").first)

        for button in buttons:
            with suppress(Exception):
                if button and button.count() > 0:
                    button.click(timeout=self.timeout * 1000)
                    return True

        with suppress(Exception):
            page.keyboard.press("Enter")
            return True
        return False

    def _click_target(self, page, target: str) -> bool:
        name_pattern = re.compile(re.escape(target), re.IGNORECASE)
        candidates = []
        for role in ("button", "link", "menuitem", "tab"):
            with suppress(Exception):
                candidates.append(page.get_by_role(role, name=name_pattern).first)

        escaped = target.replace("\\", "\\\\").replace('"', '\\"')
        selector = (
            f'button:has-text("{escaped}"), a:has-text("{escaped}"), '
            f'[aria-label*="{escaped}" i], [title*="{escaped}" i], [data-testid*="{escaped}" i]'
        )
        with suppress(Exception):
            candidates.append(page.locator(selector).first)

        for candidate in candidates:
            with suppress(Exception):
                if candidate and candidate.count() > 0:
                    candidate.click(timeout=self.timeout * 1000)
                    return True
        return False

    def _infer_input_type(self, field_name: str) -> str:
        lowered = field_name.lower()
        if "email" in lowered:
            return "email"
        if "password" in lowered or "passcode" in lowered or "pin" in lowered:
            return "password"
        if "search" in lowered:
            return "search"
        if "phone" in lowered or "mobile" in lowered:
            return "tel"
        if "url" in lowered or "website" in lowered or "link" in lowered:
            return "url"
        return "text"


def serve_directory_snapshot(directory: str | Path, entrypoint: str = "index.html", timeout: int = 15) -> dict[str, Any]:
    site_dir = Path(directory).resolve()
    if not site_dir.exists():
        raise FileNotFoundError(f"Directory does not exist: {site_dir}")

    browser = BrowserAutomation(timeout=timeout)
    port = _find_free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(site_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    url = f"http://127.0.0.1:{port}/{entrypoint}"
    try:
        _wait_until_ready(url, timeout=timeout)
        snapshot = browser.capture_page(url)
        return {
            "snapshot": snapshot.to_dict(),
            "served_from": str(site_dir),
        }
    finally:
        proc.terminate()
        with suppress(Exception):
            proc.wait(timeout=5)
        with suppress(Exception):
            proc.kill()


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: int) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    deadline = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            response = session.get(url, timeout=2)
            if response.status_code < 500:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.25)

    raise RuntimeError(f"Timed out waiting for local site preview: {last_error or url}")
