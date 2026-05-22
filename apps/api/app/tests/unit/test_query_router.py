from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.router import QueryRouter


def test_query_router_sends_quoted_query_to_exact_route() -> None:
    route = QueryRouter().classify('"needle phrase"')

    assert route.mode == "exact"
    assert route.latency_tier == 1


def test_query_router_sends_identifier_style_token_to_exact_route() -> None:
    route = QueryRouter().classify("RFC-9110")

    assert route.mode == "exact"
    assert route.latency_tier == 1
