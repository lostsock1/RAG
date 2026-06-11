"""D5: Cohen's kappa unit tests with hand-computed values."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.eval.harness.judge import cohens_kappa, split_sentences


def test_kappa_perfect_agreement():
    assert cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == pytest.approx(1.0)


def test_kappa_hand_computed():
    # a=[1,1,0,0], b=[1,0,0,0]: po=3/4; pa1=0.5, pb1=0.25
    # pe = 0.5*0.25 + 0.5*0.75 = 0.5 -> kappa = (0.75-0.5)/0.5 = 0.5
    assert cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)


def test_kappa_chance_level_is_zero():
    # Independent-looking disagreement pattern: po == pe -> 0
    a = [1, 1, 0, 0]
    b = [1, 0, 1, 0]
    # po = 2/4 = 0.5; pa1=0.5, pb1=0.5 -> pe = 0.5 -> kappa = 0
    assert cohens_kappa(a, b) == pytest.approx(0.0)


def test_kappa_degenerate_all_same_class():
    assert cohens_kappa([1, 1, 1], [1, 1, 1]) == 1.0
    assert cohens_kappa([1, 1, 1], [1, 1, 0]) == 0.0  # pe == 1 edge, po < 1


def test_kappa_validation():
    with pytest.raises(ValueError, match="equal length"):
        cohens_kappa([1], [1, 0])
    with pytest.raises(ValueError, match="non-empty"):
        cohens_kappa([], [])


def test_split_sentences_matches_verifier_family():
    assert split_sentences("One. Two! Three? ") == ["One.", "Two!", "Three?"]
