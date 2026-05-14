from __future__ import annotations


def analyze(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "sum": 0.0, "mean": 0.0}
    total = float(sum(values))
    return {"count": len(values), "sum": total, "mean": total / len(values)}
