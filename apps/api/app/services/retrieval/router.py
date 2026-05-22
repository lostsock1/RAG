from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER_STYLE_EXACT_QUERY = re.compile(r"^[A-Z0-9]+(?:[-_:/.][A-Z0-9]+)+$")


@dataclass(slots=True)
class QueryRoute:
    mode: str
    latency_tier: int


class QueryRouter:
    def classify(self, query: str) -> QueryRoute:
        normalized = query.strip()
        if normalized.startswith('"') and normalized.endswith('"') and len(normalized) >= 2:
            return QueryRoute(mode="exact", latency_tier=1)
        if _IDENTIFIER_STYLE_EXACT_QUERY.fullmatch(normalized):
            return QueryRoute(mode="exact", latency_tier=1)
        return QueryRoute(mode="semantic", latency_tier=2)
