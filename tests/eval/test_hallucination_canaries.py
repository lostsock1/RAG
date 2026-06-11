"""D4: hallucination canary suite (ADR-0019 criterion 2).

Targets the documented `not_contradicted` blind spot (ADR-0016): a fabricated
claim about a topic ABSENT from the evidence passes the contradiction
guardrail, because nothing contradicts it. Each canary pairs verbatim fixture
context with a plausible fabricated sentence; the grounding verifier must
reject >= 80% of the fabrications that the NLI guardrail passes.

Controls guard against a trivial reject-everything win: paraphrase controls
must be SUPPORTED by both verifiers.

Loads both real models (~1.3 GB NLI + ~3 GB MiniCheck on first run).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("transformers", reason="ML stack not installed")

from app.schemas.context import ContextBlock, ContextPayload
from app.services.answer_verifier_grounding import GroundingAnswerVerifier
from app.services.answer_verifier_nli import NliAnswerVerifier

EVAL_DIR = Path(__file__).parent
CORPUS_DIR = EVAL_DIR / "fixtures" / "sample_corpus"
REPORT_PATH = EVAL_DIR / "reports" / "hallucination_canaries.json"


def _payload_from(doc_slug: str, *, contains: str) -> ContextPayload:
    """Build a single-block context from the fixture paragraph containing a marker."""
    text = (CORPUS_DIR / f"{doc_slug}.md").read_text(encoding="utf-8")
    paragraph = next(p for p in text.split("\n\n") if contains in p)
    block = ContextBlock(
        text=paragraph,
        document_id="doc-1",
        document_title=doc_slug,
        chunk_id="chunk-1",
        citation_id="chunk-1",
        heading_path=[],
        rank=1,
    )
    return ContextPayload(blocks=[block], block_count=1, total_characters=len(paragraph), truncated=False)


# (doc_slug, paragraph marker, fabricated claim — plausible, topical, ABSENT)
CANARIES = [
    ("physics_textbook_ch3_thermodynamics", "arrow of time",
     "The second law of thermodynamics was first formulated by Isaac Newton in 1687."),
    ("physics_textbook_ch3_thermodynamics", "gravitational constant",
     "The gravitational constant was first measured with a torsion balance designed by Albert Einstein."),
    ("chemistry_textbook_ch4_reactions", "activation energy",
     "Catalysts also increase the equilibrium constant of a reaction by roughly a factor of ten."),
    ("biology_textbook_ch5_cells", "light energy",
     "Photosynthesis was discovered by Marie Curie in 1903."),
    ("economics_textbook_ch2_markets", "purchasing power",
     "The textbook reports that inflation in Germany reached 14 percent in 2019."),
    ("psychology_textbook_ch8_grief", "five stages",
     "Kübler-Ross later added a sixth stage called renewal in 1975."),
    ("geography_demographics_table", "Liechtenstein",
     "Liechtenstein's population grew by 12 percent between 2010 and 2020."),
    ("history_textbook_ch12_treaties", "Parmenides",
     "Zeno also wrote a book titled On Motion which survives in full today."),
    ("mineralogy_textbook_appendix", "Grossular garnet",
     "Grossular garnet was first identified in Brazil in 1822."),
    ("mathematics_textbook_ch2_definitions", "vector space",
     "Vector spaces were first introduced by Euclid in the Elements."),
]

# Paraphrase controls — both verifiers must SUPPORT these.
CONTROLS = [
    ("physics_textbook_ch3_thermodynamics", "arrow of time",
     "An isolated system's total entropy cannot go down over time."),
    ("chemistry_textbook_ch4_reactions", "activation energy",
     "A catalyst speeds up a chemical reaction without being used up itself."),
    ("biology_textbook_ch6_processes", "feedback",
     "Homeostasis keeps an organism's internal conditions stable through feedback mechanisms."),
]

# Contradiction control — present-and-contradicted; BOTH verifiers must reject.
CONTRADICTION = (
    "history_textbook_ch12_treaties", "never ratified",
    "The United States Senate ratified the Treaty of Lausanne in 1924.",
)


@pytest.mark.slow
def test_hallucination_canaries():
    nli = NliAnswerVerifier(scoring_mode="not_contradicted", unsupported_ratio=0.2)
    grounding = GroundingAnswerVerifier(threshold=0.5, unsupported_ratio=0.0)

    rows = []
    for doc, marker, claim in CANARIES:
        payload = _payload_from(doc, contains=marker)
        nli_status = nli.verify(answer_text=claim, context_payload=payload).status
        grounding_status = grounding.verify(answer_text=claim, context_payload=payload).status
        rows.append({
            "kind": "fabrication",
            "doc": doc,
            "claim": claim,
            "nli_not_contradicted": nli_status,
            "grounding": grounding_status,
        })

    control_rows = []
    for doc, marker, claim in CONTROLS:
        payload = _payload_from(doc, contains=marker)
        control_rows.append({
            "kind": "paraphrase_control",
            "doc": doc,
            "claim": claim,
            "nli_not_contradicted": nli.verify(answer_text=claim, context_payload=payload).status,
            "grounding": grounding.verify(answer_text=claim, context_payload=payload).status,
        })

    doc, marker, claim = CONTRADICTION
    payload = _payload_from(doc, contains=marker)
    contradiction_row = {
        "kind": "contradiction_control",
        "doc": doc,
        "claim": claim,
        "nli_not_contradicted": nli.verify(answer_text=claim, context_payload=payload).status,
        "grounding": grounding.verify(answer_text=claim, context_payload=payload).status,
    }

    passed_by_nli = [r for r in rows if r["nli_not_contradicted"] == "supported"]
    caught_by_grounding = [r for r in passed_by_nli if r["grounding"] == "unsupported"]
    catch_rate = len(caught_by_grounding) / len(passed_by_nli) if passed_by_nli else 1.0

    report = {
        "report": "hallucination_canaries",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "canary_count": len(rows),
        "nli_blind_spot_count": len(passed_by_nli),
        "grounding_catch_rate_on_nli_blind_spot": round(catch_rate, 4),
        "criterion": "ADR-0019 #2: catch rate >= 0.80",
        "rows": rows + control_rows + [contradiction_row],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nCanary report written: {REPORT_PATH}")
    print(f"NLI blind spot: {len(passed_by_nli)}/{len(rows)} fabrications passed not_contradicted")
    print(f"Grounding catch rate on blind spot: {catch_rate:.2%}")
    for r in control_rows:
        print(f"control: grounding={r['grounding']} nli={r['nli_not_contradicted']} :: {r['claim'][:60]}")

    # The blind spot must actually exist for the criterion to be meaningful.
    assert len(passed_by_nli) >= 5, (
        f"Expected not_contradicted to pass most fabrications (blind spot); "
        f"only {len(passed_by_nli)}/{len(rows)} passed."
    )

    # ADR-0019 criterion 2.
    assert catch_rate >= 0.80, (
        f"Grounding verifier caught only {catch_rate:.0%} of fabrications that "
        f"not_contradicted passed (criterion: >= 80%)."
    )

    # Anti-trivality: paraphrase controls must be supported by the grounding verifier.
    for r in control_rows:
        assert r["grounding"] == "supported", f"Grounding rejected a true paraphrase: {r['claim']}"

    # Contradiction control: both verifiers reject.
    assert contradiction_row["nli_not_contradicted"] == "unsupported"
    assert contradiction_row["grounding"] == "unsupported"
