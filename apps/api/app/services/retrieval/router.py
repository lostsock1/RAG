from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class QueryRoute:
    mode: str
    latency_tier: int


class QueryRouter:
    def classify(self, query: str) -> QueryRoute:
        normalized = query.strip()
        if normalized.startswith('"') and normalized.endswith('"') and len(normalized) >= 2:
            return QueryRoute(mode="exact", latency_tier=1)
        return QueryRoute(mode="semantic", latency_tier=2)
