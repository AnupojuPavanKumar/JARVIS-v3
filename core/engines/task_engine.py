import re
import logging

log = logging.getLogger("TaskEngine")

class TaskEngine:
    """
    Parses complex natural language commands into discrete sub-tasks.
    Handles splitting by temporal keywords (then, after that, next).
    """

    # Keywords that indicate a new step in a sequence
    _SPLITTERS = [
        r"\band then\b",
        r"\bthen\b",
        r"\bafter that\b",
        r"\bnext\b",
        r"\bafterward\b",
        r"\bfinally\b"
    ]

    # Compounds that look like splitters but shouldn't be split
    _COMPOUND_EXCEPTIONS = [
        r"download and install",
        r"research and develop",
        r"search and find",
        r"black and white",
        r"up and down",
        r"left and right",
        r"stop and go"
    ]

    def __init__(self):
        pass

    def parse_task(self, command: str) -> list[str]:
        """
        Splits a compound command into a list of individual tasks.
        Example: "open chrome and then search google" -> ["open chrome", "search google"]
        """
        if not command:
            return []

        # 1. Protect compound exceptions by temporary placeholder
        protected = command
        placeholders = {}
        for i, pattern in enumerate(self._COMPOUND_EXCEPTIONS):
            key = f"__PROTECTED_{i}__"
            protected = re.sub(pattern, key, protected, flags=re.IGNORECASE)
            placeholders[key] = pattern

        # 2. Split by keywords
        pattern = "|".join(self._SPLITTERS)
        parts = re.split(pattern, protected, flags=re.IGNORECASE)

        # Helper to restore placeholders in a string
        def restore_placeholders(text: str) -> str:
            result = text
            for key, val in placeholders.items():
                result = result.replace(key, val)
            return result

        # 3. Clean up parts and restore protected compounds
        clean_parts = []
        for p in parts:
            p = p.strip().rstrip(",.! ")
            if not p:
                continue

            # Special case for "and" if it's acting as a task separator
            # but only if it separates two distinct actions.
            if " and " in p:
                subparts = p.split(" and ")
                # Check if subparts are substantial
                if all(len(sp.strip()) > 3 for sp in subparts):
                    for sp in subparts:
                        final_sp = restore_placeholders(sp.strip())
                        # Recursively parse subparts for nested splitters
                        nested_parts = self._split_by_splitters(final_sp)
                        clean_parts.extend(nested_parts)
                    continue

            # Restore protected compounds
            p = restore_placeholders(p)
            if p: clean_parts.append(p)

        return clean_parts if clean_parts else [command]

    def _split_by_splitters(self, text: str) -> list[str]:
        """Split text by splitters, preserving compound exceptions."""
        # Protect compounds first
        protected = text
        placeholders = {}
        for i, pattern in enumerate(self._COMPOUND_EXCEPTIONS):
            key = f"__PROTECTED_{i}__"
            protected = re.sub(pattern, key, protected, flags=re.IGNORECASE)
            placeholders[key] = pattern

        pattern = "|".join(self._SPLITTERS)
        parts = re.split(pattern, protected, flags=re.IGNORECASE)

        def restore(text: str) -> str:
            for key, val in placeholders.items():
                text = text.replace(key, val)
            return text

        result = []
        for p in parts:
            p = p.strip().rstrip(",.! ")
            if p:
                result.append(restore(p))
        return result
