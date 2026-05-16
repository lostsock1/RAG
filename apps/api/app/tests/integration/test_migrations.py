from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine.reflection import Inspector

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
