from __future__ import annotations

def reciprocal_rank_fusion(rank_lists: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for rank_list in rank_lists:
        for rank, item in enumerate(rank_list, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return [
        item
        for item, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    ]
