from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine.reflection import Inspector
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


@pytest.fixture()
def inspector():
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'phase1.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")

        if alembic_ini_path.exists():
            config = Config(str(alembic_ini_path))
            config.set_main_option("sqlalchemy.url", database_url)

            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")

        yield inspect(engine)
        engine.dispose()


def test_phase1_tables_exist(inspector: Inspector) -> None:
    table_names = set(inspector.get_table_names())
    expected = {
        "tenants",
        "users",
        "groups",
        "user_groups",
        "documents",
        "acl_grants",
        "acl_allowed_users",
        "acl_allowed_groups",
        "audit_events",
    }
    assert expected.issubset(table_names)


def test_phase2_ingestion_tables_exist(inspector: Inspector) -> None:
    table_names = set(inspector.get_table_names())

    assert "ingestion_runs" in table_names
    assert "ingestion_stages" in table_names
    assert "parsed_artifacts" in table_names
    assert "quality_reports" in table_names

    parsed_artifact_uniques = {tuple(sorted(constraint["column_names"])) for constraint in inspector.get_unique_constraints("parsed_artifacts")}
    quality_report_uniques = {tuple(sorted(constraint["column_names"])) for constraint in inspector.get_unique_constraints("quality_reports")}

    assert ("run_id",) in parsed_artifact_uniques
    assert ("run_id",) in quality_report_uniques


def test_ingestion_reliability_hardening_upgrade_cleans_legacy_duplicates() -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'phase2-dup.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        tenant_id = str(uuid4())
        owner_user_id = str(uuid4())
        document_id_1 = str(uuid4())
        document_id_2 = str(uuid4())
        tombstone_id_1 = str(uuid4())
        tombstone_id_2 = str(uuid4())
        run_id = str(uuid4())
        stage_id_1 = str(uuid4())
        stage_id_2 = str(uuid4())

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "20260516_0004")

            connection.execute(
                text(
                    "INSERT INTO tenants (id, name, slug) VALUES (:id, 'Tenant', 'tenant')"
                ),
                {"id": tenant_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO users (id, tenant_id, email, display_name, roles)
                    VALUES (:id, :tenant_id, 'user@example.com', 'User', '[]')
                    """
                ),
                {"id": owner_user_id, "tenant_id": tenant_id},
            )
            for document_id, file_name, object_key in (
                (document_id_1, "sample.txt", "documents/tenant/hash.txt"),
                (document_id_2, "sample.md", "documents/tenant/hash.md"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO documents (
                            id,
                            tenant_id,
                            owner_user_id,
                            title,
                            source_type,
                            source_hash,
                            file_name,
                            file_size_bytes,
                            object_key,
                            ingestion_status,
                            is_tombstoned
                        ) VALUES (
                            :id,
                            :tenant_id,
                            :owner_user_id,
                            'Duplicate',
                            'loose_document',
                            'same-hash',
                            :file_name,
                            11,
                            :object_key,
                            'uploaded',
                            0
                        )
                        """
                    ),
                    {
                        "id": document_id,
                        "tenant_id": tenant_id,
                        "owner_user_id": owner_user_id,
                        "file_name": file_name,
                        "object_key": object_key,
                    },
                )

            for tombstone_id, file_name, object_key in (
                (tombstone_id_1, "sample-old.txt", "documents/tenant/hash-old.txt"),
                (tombstone_id_2, "sample-old.md", "documents/tenant/hash-old.md"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO documents (
                            id,
                            tenant_id,
                            owner_user_id,
                            title,
                            source_type,
                            source_hash,
                            file_name,
                            file_size_bytes,
                            object_key,
                            ingestion_status,
                            is_tombstoned,
                            tombstoned_at
                        ) VALUES (
                            :id,
                            :tenant_id,
                            :owner_user_id,
                            'Duplicate Tombstone',
                            'loose_document',
                            'same-hash',
                            :file_name,
                            11,
                            :object_key,
                            'uploaded',
                            1,
                            CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "id": tombstone_id,
                        "tenant_id": tenant_id,
                        "owner_user_id": owner_user_id,
                        "file_name": file_name,
                        "object_key": object_key,
                    },
                )

            connection.execute(
                text(
                    """
                    INSERT INTO ingestion_runs (
                        id,
                        document_id,
                        tenant_id,
                        status,
                        workflow_backend,
                        parser_backend,
                        source_hash
                    ) VALUES (
                        :id,
                        :document_id,
                        :tenant_id,
                        'queued',
                        'scaffold',
                        'docling-local',
                        'same-hash'
                    )
                    """
                ),
                {"id": run_id, "document_id": document_id_1, "tenant_id": tenant_id},
            )
            for stage_id in (stage_id_1, stage_id_2):
                connection.execute(
                    text(
                        """
                        INSERT INTO ingestion_stages (
                            id,
                            run_id,
                            tenant_id,
                            stage_name,
                            status,
                            details
                        ) VALUES (
                            :id,
                            :run_id,
                            :tenant_id,
                            'parse',
                            'queued',
                            '{}'
                        )
                        """
                    ),
                    {"id": stage_id, "run_id": run_id, "tenant_id": tenant_id},
                )

            command.upgrade(config, "head")

            live_documents = connection.execute(
                text(
                    """
                    SELECT id, object_key
                    FROM documents
                    WHERE tenant_id = :tenant_id
                      AND owner_user_id = :owner_user_id
                      AND source_hash = 'same-hash'
                      AND is_tombstoned = 0
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"tenant_id": tenant_id, "owner_user_id": owner_user_id},
            ).fetchall()
            tombstoned_documents = connection.execute(
                text(
                    """
                    SELECT id
                    FROM documents
                    WHERE tenant_id = :tenant_id
                      AND owner_user_id = :owner_user_id
                      AND source_hash = 'same-hash'
                      AND is_tombstoned = 1
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"tenant_id": tenant_id, "owner_user_id": owner_user_id},
            ).fetchall()
            parse_stages = connection.execute(
                text(
                    """
                    SELECT id
                    FROM ingestion_stages
                    WHERE run_id = :run_id
                      AND stage_name = 'parse'
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"run_id": run_id},
            ).fetchall()

        inspector = inspect(engine)
        document_indexes = {
            index["name"]: {
                "columns": tuple(index["column_names"]),
                "unique": index.get("unique", False),
            }
            for index in inspector.get_indexes("documents")
        }
        stage_uniques = {
            tuple(sorted(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints("ingestion_stages")
        }

        assert len(live_documents) == 1
        assert {row.id for row in live_documents} <= {document_id_1, document_id_2}
        assert len(tombstoned_documents) == 3
        assert {row.id for row in tombstoned_documents} == {tombstone_id_1, tombstone_id_2, document_id_1, document_id_2} - {live_documents[0].id}
        assert len(parse_stages) == 1
        assert {row.id for row in parse_stages} <= {stage_id_1, stage_id_2}
        assert document_indexes["ix_documents_live_owner_hash"]["columns"] == (
            "tenant_id",
            "owner_user_id",
            "source_hash",
        )
        assert bool(document_indexes["ix_documents_live_owner_hash"]["unique"]) is True
        assert ("run_id", "stage_name") in stage_uniques

        engine.dispose()


def test_ingestion_reliability_hardening_enforces_live_uniqueness_after_upgrade() -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'phase2-live-uniqueness.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        tenant_id = str(uuid4())
        owner_user_id = str(uuid4())
        live_document_id = str(uuid4())
        duplicate_live_document_id = str(uuid4())
        tombstone_id_1 = str(uuid4())
        tombstone_id_2 = str(uuid4())

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

            connection.execute(
                text("INSERT INTO tenants (id, name, slug) VALUES (:id, 'Tenant', 'tenant')"),
                {"id": tenant_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO users (id, tenant_id, email, display_name, roles)
                    VALUES (:id, :tenant_id, 'user@example.com', 'User', '[]')
                    """
                ),
                {"id": owner_user_id, "tenant_id": tenant_id},
            )

            for tombstone_id in (tombstone_id_1, tombstone_id_2):
                connection.execute(
                    text(
                        """
                        INSERT INTO documents (
                            id,
                            tenant_id,
                            owner_user_id,
                            title,
                            source_type,
                            source_hash,
                            ingestion_status,
                            is_tombstoned,
                            tombstoned_at
                        ) VALUES (
                            :id,
                            :tenant_id,
                            :owner_user_id,
                            'Tombstone',
                            'loose_document',
                            'same-hash',
                            'uploaded',
                            1,
                            CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "id": tombstone_id,
                        "tenant_id": tenant_id,
                        "owner_user_id": owner_user_id,
                    },
                )

            connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        id,
                        tenant_id,
                        owner_user_id,
                        title,
                        source_type,
                        source_hash,
                        ingestion_status,
                        is_tombstoned
                    ) VALUES (
                        :id,
                        :tenant_id,
                        :owner_user_id,
                        'Live',
                        'loose_document',
                        'same-hash',
                        'uploaded',
                        0
                    )
                    """
                ),
                {
                    "id": live_document_id,
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_user_id,
                },
            )

            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO documents (
                            id,
                            tenant_id,
                            owner_user_id,
                            title,
                            source_type,
                            source_hash,
                            ingestion_status,
                            is_tombstoned
                        ) VALUES (
                            :id,
                            :tenant_id,
                            :owner_user_id,
                            'Live Duplicate',
                            'loose_document',
                            'same-hash',
                            'uploaded',
                            0
                        )
                        """
                    ),
                    {
                        "id": duplicate_live_document_id,
                        "tenant_id": tenant_id,
                        "owner_user_id": owner_user_id,
                    },
                )

        engine.dispose()
