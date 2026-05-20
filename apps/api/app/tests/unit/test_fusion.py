from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_prefers_hits_present_in_multiple_rank_lists() -> None:
    fused = reciprocal_rank_fusion(
        [
            ["chunk-a", "chunk-b"],
            ["chunk-b", "chunk-c"],
        ]
    )

    assert fused[0] == "chunk-b"
