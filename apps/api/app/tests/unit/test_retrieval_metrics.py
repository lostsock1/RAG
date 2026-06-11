"""C2: retrieval metric unit tests with hand-computed values."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.eval.harness.scorer import mrr_at_k, ndcg_at_k, recall_at_k

RANKED = ["a", "b", "c", "d"]
RELEVANT = {"b", "d"}


def test_recall_at_k_hand_computed():
    assert recall_at_k(RANKED, RELEVANT, k=1) == 0.0
    assert recall_at_k(RANKED, RELEVANT, k=2) == 0.5
    assert recall_at_k(RANKED, RELEVANT, k=4) == 1.0
    # k beyond list length: no error, same as full list
    assert recall_at_k(RANKED, RELEVANT, k=10) == 1.0


def test_mrr_at_k_hand_computed():
    # First relevant is "b" at rank 2 -> 1/2
    assert mrr_at_k(RANKED, RELEVANT, k=4) == 0.5
    # Cut off before any relevant -> 0
    assert mrr_at_k(RANKED, RELEVANT, k=1) == 0.0
    # Relevant at rank 1
    assert mrr_at_k(["b", "a"], RELEVANT, k=2) == 1.0


def test_ndcg_at_k_hand_computed():
    # Hits at ranks 2 and 4: DCG = 1/log2(3) + 1/log2(5)
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    # Ideal: both relevant at ranks 1 and 2: IDCG = 1/log2(2) + 1/log2(3)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(RANKED, RELEVANT, k=4) == pytest.approx(dcg / idcg)
    # Perfect ranking -> 1.0
    assert ndcg_at_k(["b", "d", "a", "c"], RELEVANT, k=4) == pytest.approx(1.0)
    # No relevant retrieved -> 0.0
    assert ndcg_at_k(["a", "c"], RELEVANT, k=2) == 0.0


def test_ndcg_idcg_capped_at_k():
    # 3 relevant docs but k=2: ideal can only place 2 -> a perfect top-2 scores 1.0
    relevant = {"x", "y", "z"}
    assert ndcg_at_k(["x", "y"], relevant, k=2) == pytest.approx(1.0)


def test_metrics_reject_empty_relevant_set():
    for fn in (recall_at_k, mrr_at_k, ndcg_at_k):
        with pytest.raises(ValueError, match="non-empty"):
            fn(RANKED, set(), k=4)


def test_metrics_reject_nonpositive_k():
    for fn in (recall_at_k, mrr_at_k, ndcg_at_k):
        with pytest.raises(ValueError, match="positive"):
            fn(RANKED, RELEVANT, k=0)


# ---------------------------------------------------------------------------
# Group-aware metrics (per-span equivalence groups)
# ---------------------------------------------------------------------------

from tests.eval.harness.scorer import (  # noqa: E402
    grouped_mrr_at_k,
    grouped_ndcg_at_k,
    grouped_recall_at_k,
)


def test_grouped_recall_any_member_satisfies_group():
    groups = [{"leaf1", "parent1"}, {"z"}]
    # "leaf1" retrieved at rank 1: group 1 satisfied; group 2 not.
    assert grouped_recall_at_k(["leaf1", "b", "c"], groups, k=3) == 0.5
    # Both members of group 1 retrieved must not double-count.
    assert grouped_recall_at_k(["leaf1", "parent1", "c"], groups, k=3) == 0.5
    assert grouped_recall_at_k(["leaf1", "z"], groups, k=2) == 1.0


def test_grouped_mrr_first_hit_of_any_group():
    groups = [{"a", "a2"}, {"b"}]
    assert grouped_mrr_at_k(["x", "a2", "b"], groups, k=3) == 0.5
    assert grouped_mrr_at_k(["x", "y"], groups, k=2) == 0.0


def test_grouped_ndcg_hand_computed():
    groups = [{"a", "a2"}, {"z"}]
    # Group 1 first satisfied at rank 1; group 2 never. DCG = 1/log2(2) = 1.
    # IDCG (2 groups) = 1/log2(2) + 1/log2(3).
    idcg = 1.0 + 1.0 / math.log2(3)
    assert grouped_ndcg_at_k(["a", "b", "c"], groups, k=3) == pytest.approx(1.0 / idcg)
    # Second member of the same group earns nothing extra.
    assert grouped_ndcg_at_k(["a", "a2", "c"], groups, k=3) == pytest.approx(1.0 / idcg)
    # Perfect: one member of each group at top ranks.
    assert grouped_ndcg_at_k(["a2", "z"], groups, k=2) == pytest.approx(1.0)


def test_grouped_metrics_validation():
    with pytest.raises(ValueError, match="non-empty"):
        grouped_recall_at_k(["a"], [], k=1)
    with pytest.raises(ValueError, match="non-empty"):
        grouped_ndcg_at_k(["a"], [{"a"}, set()], k=1)
    with pytest.raises(ValueError, match="positive"):
        grouped_mrr_at_k(["a"], [{"a"}], k=0)
