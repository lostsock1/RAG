"""
Phase 3 search-path latency benchmark.

Measures round-trip latency for POST /api/v1/search through the full API path:
  validation -> ACL resolution -> service orchestration -> response shaping -> audit write.

Uses the same integration-test patterns (SQLite + Alembic migrations + seeded documents
+ fake retriever) so the benchmark exercises real code paths without external services.

Usage:
    python -m pytest apps/api/app/tests/benchmark_search_latency.py -v -s

Exit criteria:
    p50 < 500 ms
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.base import session_factory
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app


# ---------------------------------------------------------------------------
# Fake retriever -- returns 5 realistic hits per query
# ---------------------------------------------------------------------------

class BenchmarkRetriever:
    """Deterministic fake retriever that returns 5 hits per query.

    Simulates realistic result-shaping overhead by returning varied
    document_ids, scores, text lengths, and heading paths.
    """

    def __init__(self, document_ids: list[str]) -> None:
        self.document_ids = document_ids
        self.query_count = 0

    def search(self, query: object) -> list[dict]:
        self.query_count += 1
        hits: list[dict] = []
        for i in range(5):
            doc_idx = i % len(self.document_ids)
            hits.append({
                'document_id': self.document_ids[doc_idx],
                'chunk_id': f'chunk-bench-{self.query_count}-{i}',
                'score': round(0.95 - i * 0.08, 2),
                'text': (
                    f'Benchmark hit {i} for query {self.query_count}. '
                    'This text simulates a realistic chunk of retrieved content '
                    'that would normally come from the hybrid retrieval pipeline. '
                    'It includes enough words to exercise response serialization.'
                ),
                'page_start': i + 1,
                'page_end': i + 1,
                'heading_path': [f'Section {i}', f'Subsection {i}'],
                'route': 'semantic',
            })
        return hits


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_corpus(
    *,
    tenant_id: object,
    owner_id: object,
    user_id: object,
    group_id: object,
    num_documents: int = 20,
) -> list[str]:
    """Seed ~20 documents with ACL grants and return their string IDs."""
    with session_factory() as session:
        # Tenant + users + group
        session.add(Tenant(id=tenant_id, name='Benchmark Tenant', slug='bench-tenant'))
        session.add_all([
            User(
                id=owner_id,
                tenant_id=tenant_id,
                email='owner@bench.test',
                display_name='Benchmark Owner',
                roles=['editor'],
            ),
            User(
                id=user_id,
                tenant_id=tenant_id,
                email='user@bench.test',
                display_name='Benchmark User',
                roles=['editor'],
            ),
        ])
        session.add(Group(id=group_id, tenant_id=tenant_id, name='bench-group'))
        session.add(UserGroup(user_id=user_id, group_id=group_id))
        session.flush()

        document_ids: list[str] = []
        for i in range(num_documents):
            visibility = 'group' if i % 3 == 0 else 'tenant' if i % 3 == 1 else 'public'
            doc = Document(
                tenant_id=tenant_id,
                owner_user_id=owner_id,
                title=f'Benchmark Document {i:03d}',
                source_type='loose_document',
                source_hash=f'bench-hash-{i}',
                file_name=f'doc_{i:03d}.txt',
                file_size_bytes=256,
                object_key=f'documents/doc_{i:03d}.txt',
                ingestion_status='completed',
            )
            session.add(doc)
            session.flush()

            acl_grant = AclGrant(
                document_id=doc.id,
                owner_user_id=owner_id,
                tenant_id=tenant_id,
                visibility=visibility,
                sensitivity='internal',
            )
            session.add(acl_grant)
            session.flush()

            session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=user_id))
            if visibility == 'group':
                session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_id))

            document_ids.append(str(doc.id))

        session.commit()

    return document_ids


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(*, num_requests: int = 100) -> dict:
    """Run the benchmark and return latency statistics."""
    tenant_id = uuid4()
    owner_id = uuid4()
    user_id = uuid4()
    group_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / 'bench-search.db'
        database_url = f'sqlite:///{db_path}'
        engine = create_engine(database_url)

        # Run migrations
        alembic_cfg = Config(str(Path('infra/migrations/alembic.ini')))
        alembic_cfg.set_main_option('sqlalchemy.url', database_url)
        with engine.begin() as conn:
            alembic_cfg.attributes['connection'] = conn
            command.upgrade(alembic_cfg, 'head')

        session_factory.configure(bind=engine)

        try:
            document_ids = _seed_corpus(
                tenant_id=tenant_id,
                owner_id=owner_id,
                user_id=user_id,
                group_id=group_id,
            )

            retriever = BenchmarkRetriever(document_ids=document_ids)

            context = RequestContext(
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                group_ids=[str(group_id)],
                roles=['editor'],
                scopes=['documents:read'],
            )

            app.dependency_overrides[get_request_context] = lambda: context
            app.state.search_retriever = retriever

            client = TestClient(app)

            # Warm-up: 5 requests to prime SQLite page cache
            for _ in range(5):
                client.post('/api/v1/search', json={'query': 'warmup query', 'top_k': 5})

            # Reset query counter after warm-up
            retriever.query_count = 0

            # Measured requests
            latencies_ms: list[float] = []
            queries = [
                f'benchmark query {i} with some realistic terms'
                for i in range(num_requests)
            ]

            for query_text in queries:
                start = time.perf_counter()
                response = client.post(
                    '/api/v1/search',
                    json={'query': query_text, 'top_k': 5},
                )
                elapsed_ms = (time.perf_counter() - start) * 1000.0

                assert response.status_code == 200, (
                    f'Unexpected status {response.status_code}: {response.text}'
                )
                latencies_ms.append(elapsed_ms)

        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, 'search_retriever'):
                delattr(app.state, 'search_retriever')
            session_factory.configure(bind=None)
            engine.dispose()

    # Compute statistics
    sorted_latencies = sorted(latencies_ms)
    p50 = sorted_latencies[int(len(sorted_latencies) * 0.50)]
    p90 = sorted_latencies[int(len(sorted_latencies) * 0.90)]
    p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)]

    stats = {
        'num_requests': num_requests,
        'num_documents': len(document_ids),
        'min_ms': round(sorted_latencies[0], 2),
        'max_ms': round(sorted_latencies[-1], 2),
        'mean_ms': round(statistics.mean(sorted_latencies), 2),
        'median_ms': round(statistics.median(sorted_latencies), 2),
        'stdev_ms': round(statistics.stdev(sorted_latencies), 2) if len(sorted_latencies) > 1 else 0.0,
        'p50_ms': round(p50, 2),
        'p90_ms': round(p90, 2),
        'p99_ms': round(p99, 2),
        'p50_pass': p50 < 500.0,
    }
    return stats


def print_report(stats: dict) -> None:
    """Print a formatted benchmark report."""
    print('\n' + '=' * 60)
    print('  Phase 3 Search Path Latency Benchmark')
    print('=' * 60)
    print(f'  Requests:       {stats["num_requests"]}')
    print(f'  Documents:      {stats["num_documents"]}')
    print(f'  Hits/query:     5 (fake retriever)')
    print('-' * 60)
    print(f'  Min:            {stats["min_ms"]:>8.2f} ms')
    print(f'  Max:            {stats["max_ms"]:>8.2f} ms')
    print(f'  Mean:           {stats["mean_ms"]:>8.2f} ms')
    print(f'  Median (p50):   {stats["median_ms"]:>8.2f} ms')
    print(f'  Std Dev:        {stats["stdev_ms"]:>8.2f} ms')
    print(f'  p90:            {stats["p90_ms"]:>8.2f} ms')
    print(f'  p99:            {stats["p99_ms"]:>8.2f} ms')
    print('-' * 60)
    verdict = 'PASS' if stats['p50_pass'] else 'FAIL'
    print(f'  p50 < 500ms:    {verdict}  (p50 = {stats["p50_ms"]} ms)')
    print('=' * 60 + '\n')


# ---------------------------------------------------------------------------
# pytest entry point
# ---------------------------------------------------------------------------

def test_search_latency_benchmark() -> None:
    """Run 100 search requests and assert p50 < 500ms."""
    stats = run_benchmark(num_requests=100)
    print_report(stats)

    assert stats['p50_pass'], (
        f"p50 latency {stats['p50_ms']}ms exceeds 500ms threshold. "
        f"Full stats: {stats}"
    )


if __name__ == '__main__':
    stats = run_benchmark(num_requests=100)
    print_report(stats)
    sys.exit(0 if stats['p50_pass'] else 1)
