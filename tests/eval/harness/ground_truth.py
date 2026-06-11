"""Resolve span-anchored ground truth to chunk IDs (master plan C1).

Evidence spans are verbatim quotes from fixture documents. At eval time they
are resolved to the IDs of every ingested chunk (leaf or parent) whose text
contains the span. Content anchoring means the ground truth survives
re-chunking; a span that stops matching raises instead of silently shrinking
the relevant set (ground-truth rot guard).
"""
from __future__ import annotations

from uuid import UUID

from tests.eval.harness.loader import EvidenceSpan

# The fixture-corpus questions with span-anchored ground truth (kept in one
# place; test_nli_faithfulness.py predates this module and carries its own copy).
FIXTURE_ANSWERED_IDS = {
    "h01", "h04", "h10", "h12", "h13",
    "h16", "h19", "h25", "h29", "h31",
    "n03", "n06", "n12", "n15", "n19",
}


def resolve_expected_chunk_groups(
    *,
    evidence: list[EvidenceSpan],
    document_ids_by_slug: dict[str, UUID],
) -> list[set[str]]:
    """Return one equivalence group of chunk IDs per evidence span.

    A span typically matches both a leaf chunk and its parent (both contain
    the text, both are indexed). Retrieving *any* member of a group delivers
    the evidence, so metrics must score per group — raw chunk-level recall
    would penalize the leaf/parent duplication meaninglessly (first baseline
    run measured exactly that artifact: recall 0.5 with MRR 1.0 across the
    board).

    Raises
    ------
    KeyError
        If an evidence entry references a document slug that was not ingested.
    ValueError
        If a span matches zero chunks of its document (ground-truth rot).
    """
    from app.repositories.chunks import get_chunks_as_schemas

    groups: list[set[str]] = []
    for entry in evidence:
        if entry.doc not in document_ids_by_slug:
            raise KeyError(
                f"Evidence references unknown document slug '{entry.doc}'. "
                f"Ingested slugs: {sorted(document_ids_by_slug)}"
            )
        document_id = document_ids_by_slug[entry.doc]
        chunks = get_chunks_as_schemas(document_id=document_id)
        matching = {str(c.id) for c in chunks if c.id is not None and entry.span in c.text}
        if not matching:
            raise ValueError(
                f"Evidence span resolved to zero chunks of '{entry.doc}' — "
                f"ground-truth rot or chunker drift. Span: {entry.span!r}"
            )
        groups.append(matching)
    return groups


def resolve_expected_chunk_ids(
    *,
    evidence: list[EvidenceSpan],
    document_ids_by_slug: dict[str, UUID],
) -> set[str]:
    """Union of all matching chunk IDs (group structure flattened)."""
    groups = resolve_expected_chunk_groups(
        evidence=evidence, document_ids_by_slug=document_ids_by_slug
    )
    return set().union(*groups)
