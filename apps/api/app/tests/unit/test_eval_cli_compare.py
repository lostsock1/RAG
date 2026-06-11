"""C4: baseline-comparison mode of the eval CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.eval.harness.cli import compare_reports, main


def _write_report(path: Path, recall10: float, ndcg10: float, mrr10: float) -> Path:
    path.write_text(json.dumps({
        "aggregates": {"recall@10": recall10, "ndcg@10": ndcg10, "mrr@10": mrr10}
    }), encoding="utf-8")
    return path


def test_compare_reports_no_regression(tmp_path: Path):
    base = _write_report(tmp_path / "base.json", 0.80, 0.70, 0.75)
    cand = _write_report(tmp_path / "cand.json", 0.79, 0.71, 0.76)  # -0.01 within tolerance
    assert compare_reports(base, cand) == []


def test_compare_reports_detects_regression(tmp_path: Path):
    base = _write_report(tmp_path / "base.json", 0.80, 0.70, 0.75)
    cand = _write_report(tmp_path / "cand.json", 0.75, 0.70, 0.75)  # -0.05 > 0.02
    regressions = compare_reports(base, cand)
    assert len(regressions) == 1
    assert "recall@10" in regressions[0]


def test_cli_compare_exits_nonzero_on_regression(tmp_path: Path):
    base = _write_report(tmp_path / "base.json", 0.80, 0.70, 0.75)
    cand = _write_report(tmp_path / "cand.json", 0.70, 0.70, 0.75)
    with pytest.raises(SystemExit) as exc_info:
        main(["--compare-baseline", str(base), "--candidate", str(cand)])
    assert exc_info.value.code == 1


def test_cli_compare_advisory_exits_zero_on_regression(tmp_path: Path):
    base = _write_report(tmp_path / "base.json", 0.80, 0.70, 0.75)
    cand = _write_report(tmp_path / "cand.json", 0.70, 0.70, 0.75)
    main(["--compare-baseline", str(base), "--candidate", str(cand), "--advisory"])  # no raise


def test_cli_compare_requires_candidate(tmp_path: Path):
    base = _write_report(tmp_path / "base.json", 0.80, 0.70, 0.75)
    with pytest.raises(SystemExit):
        main(["--compare-baseline", str(base)])
