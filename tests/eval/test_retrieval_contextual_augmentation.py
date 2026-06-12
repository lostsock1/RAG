"""E2 bake-off: contextual chunk augmentation arms vs committed baseline (ADR-0020).

Augmentation changes the *embedding/BM25 input* (``Chunk.search_text``), so the
augmented arms cannot reuse the session-scoped ``eval_stack`` (which must stay
byte-identical for baseline reproducibility — see its conftest docstring). Each
arm stands up its own SQLite + in-memory-Qdrant + BGE-M3 stack with a
contextualizer injected, re-ingests the same 27-doc corpus, and is measured on
the same 60 evidence-backed questions against the *committed* baseline report.

DECISION RULE — frozen in ADR-0020 BEFORE this measurement. Adopt an arm as
production default iff (MRR@10 or nDCG@10 lift >= +0.02 over the committed
post-distractor baseline) AND (recall@10 drop <= 0.02) AND ingest cost is
acknowledged. Tie-breaker: if both arms pass, breadcrumb wins unless llm's
lift exceeds breadcrumb's by >= +0.02 on mrr@10 or ndcg@10.

Measurement scope (recorded, not hidden): the eval rig is dense-only (its
OpenSearch retriever is a stub), so augmentation is measured through the
embedding side only. The contextual-BM25 share of Anthropic's reported gain
(35% -> 49% failure-rate reduction) is structurally invisible here.

POSITIVE CONTROL — mandatory (E1 lesson): each arm must prove augmentation
actually happened (contextualize stage counts > 0, leaf chunks persisted with
non-empty ``context_prefix``, ``search_text != text``). A silently unaugmented
arm would fraudulently reproduce the baseline as a "no lift" result.

The llm arm makes one ppq.ai call per leaf chunk (~3 s x ~313 chunks ~= 16 min,
one-time, persisted); requires PPQ_API_KEY, skips otherwise.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select

from tests.eval.conftest import (
    _EvalSearchSourcesRepo,
    _MarkdownParser,
    _StubOpenSearchRetriever,
    _ingest_corpus_documents,
)
from tests.eval.harness.ground_truth import resolve_expected_chunk_groups
from tests.eval.harness.loader import load_dataset
from tests.eval.harness.scorer import grouped_mrr_at_k, grouped_ndcg_at_k, grouped_recall_at_k

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"
BASELINE_REPORT_PATH = EVAL_DIR / "reports" / "retrieval_baseline.json"
REPORT_PATH = EVAL_DIR / "reports" / "retrieval_contextual_augmentation.json"

K_VALUES = (5, 10, 20)
TOP_K = 20

QUALITY_LIFT_BAR = 0.02        # frozen (ADR-0020): MRR@10 / nDCG@10 significance bar
RECALL_REGRESSION_BAR = 0.02   # frozen (ADR-0020): recall@10 guard
TIE_BREAK_EXTRA_LIFT = 0.02    # frozen (ADR-0020): llm must beat breadcrumb by this
PREFIX_COVERAGE_FLOOR = 0.9    # positive control: share of leaves that must carry a prefix


@contextmanager
def _augmented_stack(*, contextualizer, embedder):
    """Stand up an isolated eval stack with the contextualizer injected.

    Mirrors conftest.eval_stack construction (SQLite + alembic, in-memory
    Qdrant, mock OpenSearch, markdown parser) with the committed-baseline
    retrieval shape: stub reranker, parent expansion OFF, dense-only. Saves
    and restores the global session_factory bind so the session-scoped
    eval_stack (and any later test) is unaffected.
    """
    from app.db.base import session_factory
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer
    from app.services.indexers.qdrant_indexer import QdrantVectorIndexer
    from app.services.retrieval.hybrid_retriever import HybridSearchRetriever
    from app.services.retrieval.qdrant_retriever import QdrantRetriever
    from app.services.retrieval.query_embedder import BgeM3QueryEmbedder
    from app.services.retrieval.reranker import StubReranker
    from app.services.retrieval.router import QueryRouter
    from app.services.retrieval.search_service import SearchService
    from app.services.storage import LocalFilesystemStorageAdapter
    from app.workflows.dispatcher import InProcessDispatcher
    from app.core.request_context import RequestContext

    previous_bind = session_factory.kw.get("bind")
    tenant_id = UUID("00000000-0000-0000-0000-0000000000a1")
    user_id = UUID("00000000-0000-0000-0000-0000000000a2")

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'eval-augmented.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path("infra/migrations/alembic.ini")))
        config.set_main_option("sqlalchemy.url", database_url)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)
        try:
            with session_factory() as session:
                session.add(Tenant(id=tenant_id, name="Aug Tenant", slug="eval-aug"))
                session.add(
                    User(
                        id=user_id,
                        tenant_id=tenant_id,
                        email="aug@test.com",
                        display_name="Aug User",
                        roles=["editor"],
                    )
                )
                session.commit()

            storage = LocalFilesystemStorageAdapter(root_dir=Path(tmp_dir) / "storage")
            qdrant_indexer = QdrantVectorIndexer(collection_name="eval_chunks_aug", _in_memory=True)
            opensearch_indexer = OpenSearchLexicalIndexer(index_name="eval_chunks_aug", _mock=True)
            dispatcher = InProcessDispatcher(
                parser=_MarkdownParser(),
                parser_backend="docling-local",
                parser_profile="local-cpu",
                storage=storage,
                embedder=embedder,
                vector_indexer=qdrant_indexer,
                lexical_indexer=opensearch_indexer,
                contextualizer=contextualizer,
            )

            ingest_started = time.perf_counter()
            document_ids, document_ids_by_slug = _ingest_corpus_documents(
                dispatcher=dispatcher,
                storage=storage,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            ingest_seconds = round(time.perf_counter() - ingest_started, 1)

            retriever = HybridSearchRetriever(
                router=QueryRouter(),
                lexical_retriever=_StubOpenSearchRetriever(),
                vector_retriever=QdrantRetriever(
                    client=qdrant_indexer._ensure_client(),
                    collection_name="eval_chunks_aug",
                ),
                query_embedder=BgeM3QueryEmbedder(embedder=embedder),
                search_sources_repository=_EvalSearchSourcesRepo(),
                reranker=StubReranker(),
                rerank_candidate_limit=20,
            )
            context = RequestContext(
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                group_ids=["eval-group"],
                roles=["eval"],
                scopes=["documents:read"],
            )
            yield {
                "search_service": SearchService(retriever=retriever),
                "context": context,
                "document_ids": document_ids,
                "document_ids_by_slug": document_ids_by_slug,
                "ingest_seconds": ingest_seconds,
            }
        finally:
            session_factory.configure(bind=previous_bind)
            engine.dispose()


def _positive_control(document_ids: list[UUID]) -> dict:
    """Prove augmentation happened — counts from stage details and chunk rows."""
    from app.db.base import session_factory
    from app.db.models.chunk import Chunk as ChunkModel
    from app.db.models.ingestion import IngestionStage
    from app.repositories.chunks import get_chunks_as_schemas

    with session_factory() as session:
        stages = list(
            session.scalars(
                select(IngestionStage).where(IngestionStage.stage_name == "contextualize")
            ).all()
        )
        contextualized_count = sum((s.details or {}).get("contextualized_count", 0) for s in stages)
        rows_updated = sum((s.details or {}).get("rows_updated", 0) for s in stages)
        leaf_total = len(
            session.scalars(select(ChunkModel.id).where(ChunkModel.parent_id.is_not(None))).all()
        )

    prefixed = 0
    search_text_differs = 0
    for document_id in document_ids:
        for chunk in get_chunks_as_schemas(document_id=document_id):
            if chunk.parent_id is None:
                continue
            if chunk.context_prefix:
                prefixed += 1
                if chunk.search_text != chunk.text:
                    search_text_differs += 1

    return {
        "contextualize_stage_count": len(stages),
        "contextualized_count": contextualized_count,
        "rows_updated": rows_updated,
        "leaf_chunk_count": leaf_total,
        "leaves_with_prefix": prefixed,
        "prefixed_with_distinct_search_text": search_text_differs,
    }


def _measure_arm(stack, questions) -> list[dict]:
    from app.schemas.search import SearchRequest

    per_question: list[dict] = []
    for question in questions:
        groups = resolve_expected_chunk_groups(
            evidence=question.evidence,
            document_ids_by_slug=stack["document_ids_by_slug"],
        )
        assert groups, f"{question.id}: empty evidence groups"
        response = stack["search_service"].search(
            context=stack["context"],
            payload=SearchRequest(query=question.query, top_k=TOP_K),
        )
        ranked_ids = [item.chunk_id for item in response.items if item.chunk_id]
        metrics = {}
        for k in K_VALUES:
            metrics[f"recall@{k}"] = round(grouped_recall_at_k(ranked_ids, groups, k), 4)
            metrics[f"ndcg@{k}"] = round(grouped_ndcg_at_k(ranked_ids, groups, k), 4)
        metrics["mrr@10"] = round(grouped_mrr_at_k(ranked_ids, groups, 10), 4)
        per_question.append(
            {
                "question_id": question.id,
                "type": question.type,
                "language": question.language,
                "evidence_group_count": len(groups),
                "retrieved_count": len(ranked_ids),
                "metrics": metrics,
            }
        )
    return per_question


METRIC_KEYS = [f"recall@{k}" for k in K_VALUES] + [f"ndcg@{k}" for k in K_VALUES] + ["mrr@10"]


def _aggregate(per_question: list[dict]) -> dict:
    def mean(metric: str) -> float:
        return round(sum(r["metrics"][metric] for r in per_question) / len(per_question), 4)

    return {m: mean(m) for m in METRIC_KEYS}


def _quality_pass(lifts: dict) -> bool:
    return (
        lifts["mrr@10"] >= QUALITY_LIFT_BAR or lifts["ndcg@10"] >= QUALITY_LIFT_BAR
    ) and lifts["recall@10"] >= -RECALL_REGRESSION_BAR


@pytest.mark.slow
def test_retrieval_contextual_augmentation_bakeoff():
    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set — the llm arm cannot run, bake-off incomplete")

    from app.services.contextualizers.breadcrumb import BreadcrumbContextualizer
    from app.services.contextualizers.llm import LlmChunkContextualizer
    from app.services.embedders.bge_m3 import BgeM3Embedder

    dataset = load_dataset(HELDOUT_PATH)
    questions = [q for q in dataset.questions if q.evidence]
    assert len(questions) >= 60

    baseline = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))
    baseline_agg = baseline["aggregates"]

    embedder = BgeM3Embedder()  # shared across arms; weights load once

    arms: dict[str, dict] = {}
    arm_specs = [
        ("breadcrumb", lambda: BreadcrumbContextualizer()),
        (
            "llm",
            lambda: LlmChunkContextualizer(
                base_url="https://api.ppq.ai/v1",
                api_key=api_key,
                model_name="meta-llama/Llama-3.3-70B-Instruct",
                max_output_tokens=128,
            ),
        ),
    ]

    for arm_name, make_contextualizer in arm_specs:
        with _augmented_stack(contextualizer=make_contextualizer(), embedder=embedder) as stack:
            control = _positive_control(stack["document_ids"])

            # POSITIVE CONTROL — fail loudly before scoring if the arm did not
            # actually augment (a silent no-op would reproduce the baseline).
            assert control["contextualized_count"] > 0, f"{arm_name}: no chunks contextualized"
            assert control["leaves_with_prefix"] >= int(
                PREFIX_COVERAGE_FLOOR * control["leaf_chunk_count"]
            ), f"{arm_name}: prefix coverage below floor — {control}"
            assert (
                control["prefixed_with_distinct_search_text"] == control["leaves_with_prefix"]
            ), f"{arm_name}: prefixed chunks whose search_text == text — {control}"

            per_question = _measure_arm(stack, questions)
            aggregates = _aggregate(per_question)
            lifts = {m: round(aggregates[m] - baseline_agg[m], 4) for m in METRIC_KEYS}
            arms[arm_name] = {
                "positive_control": control,
                "ingest_seconds": stack["ingest_seconds"],
                "aggregates": aggregates,
                "lifts_vs_baseline": lifts,
                "quality_pass": _quality_pass(lifts),
                "per_question": per_question,
            }
            print(f"\n[{arm_name}] control={control} ingest={stack['ingest_seconds']}s")
            print(f"[{arm_name}] aggregates={json.dumps(aggregates)}")
            print(f"[{arm_name}] lifts={json.dumps(lifts)}")

    arms["llm"]["ingest_seconds_per_leaf"] = round(
        arms["llm"]["ingest_seconds"] / max(arms["llm"]["positive_control"]["leaf_chunk_count"], 1),
        2,
    )

    breadcrumb_pass = arms["breadcrumb"]["quality_pass"]
    llm_pass = arms["llm"]["quality_pass"]
    if breadcrumb_pass and llm_pass:
        bc, lm = arms["breadcrumb"]["lifts_vs_baseline"], arms["llm"]["lifts_vs_baseline"]
        llm_wins_tiebreak = (
            lm["mrr@10"] - bc["mrr@10"] >= TIE_BREAK_EXTRA_LIFT
            or lm["ndcg@10"] - bc["ndcg@10"] >= TIE_BREAK_EXTRA_LIFT
        )
        adopt = "llm" if llm_wins_tiebreak else "breadcrumb"
    elif breadcrumb_pass:
        adopt = "breadcrumb"
    elif llm_pass:
        adopt = "llm"
    else:
        adopt = None

    report = {
        "report": "retrieval_contextual_augmentation",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_count": len(questions),
        "rig": {
            "dense": "BGE-M3 (real) via in-memory Qdrant; embed input = search_text",
            "lexical": (
                "disabled (stub) — dense-only rig; the contextual-BM25 share of the "
                "technique's reported gain is not measurable here"
            ),
            "reranker": "stub (committed-baseline shape)",
            "parent_expansion": "disabled (committed-baseline shape)",
            "top_k": TOP_K,
            "corpus_documents": 27,
        },
        "decision_rule": {
            "frozen": (
                "ADR-0020: adopt an arm iff (MRR@10 or nDCG@10 lift >= +0.02 over the "
                "committed post-distractor baseline) AND recall@10 drop <= 0.02 AND "
                "ingest cost acknowledged; if both arms pass, breadcrumb wins unless "
                "llm exceeds its lift by >= +0.02 on mrr@10 or ndcg@10"
            ),
            "breadcrumb_quality_pass": breadcrumb_pass,
            "llm_quality_pass": llm_pass,
            "adopt_arm": adopt,
        },
        "baseline_reference": {m: baseline_agg[m] for m in METRIC_KEYS},
        "arms": arms,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nBake-off written: {REPORT_PATH}")
    print("decision:", json.dumps(report["decision_rule"]))

    # Measurement integrity only — the frozen rule is applied to the report.
    for arm_name, arm in arms.items():
        assert len(arm["per_question"]) >= 60, arm_name
        assert arm["aggregates"]["recall@20"] > 0.0, arm_name
