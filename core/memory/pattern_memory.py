from __future__ import annotations

from core.tools.long_term_memory import get_memory_instance


class PatternMemory:
    def add_pattern(self, task: str, pattern: str) -> str:
        return get_memory_instance().commit_memory(task, pattern)

    def search(self, query: str) -> str:
        return get_memory_instance().search_memory(query)


_instance: PatternMemory | None = None


def get_pattern_memory() -> PatternMemory:
    global _instance
    if _instance is None:
        _instance = PatternMemory()
    return _instance
