from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.api.routes.chat import _cached_nli_verifier


def test_nli_verifier_is_process_cached_per_configuration():
    """ADR-0018 §6: constructing NliAnswerVerifier per request reloads model
    weights on every chat call. Same configuration must yield the same instance."""
    a = _cached_nli_verifier(0.5, "not_contradicted", 0.2)
    b = _cached_nli_verifier(0.5, "not_contradicted", 0.2)
    assert a is b

    c = _cached_nli_verifier(0.5, "entailment", 0.0)
    assert c is not a
