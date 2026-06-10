from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.caches import reset_dependency_caches as _reset_dependency_caches


@pytest.fixture
def reset_dependency_caches():
    """Clear cached Settings/OIDC verifier before and after the test (P2-2)."""
    _reset_dependency_caches()
    yield
    _reset_dependency_caches()
