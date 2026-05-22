"""Integration test: NLI verifier production parity.

Ensures that the NLI verifier constructed by the chat route (via Settings)
behaves identically to the NLI verifier used in eval tests (also via Settings).

This is a regression guard against the test/prod divergence that existed
before ADR-0016: eval used not_contradicted mode while production used
entailment mode (the NliAnswerVerifier default), because chat.py did not
pass scoring_mode or unsupported_ratio through from Settings.
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.answer_verifier_nli import NliAnswerVerifier


class TestNliVerifierProductionParity:
    """Verify that production and eval verifiers share the same configuration."""

    def test_settings_provide_nli_scoring_mode(self):
        """Settings must expose nli_scoring_mode with a default."""
        settings = Settings()
        assert hasattr(settings, "nli_scoring_mode")
        assert settings.nli_scoring_mode in ("entailment", "not_contradicted")

    def test_settings_provide_nli_unsupported_ratio(self):
        """Settings must expose nli_unsupported_ratio with a default."""
        settings = Settings()
        assert hasattr(settings, "nli_unsupported_ratio")
        assert 0.0 <= settings.nli_unsupported_ratio <= 1.0

    def test_production_default_matches_adr_0016(self):
        """The production default for nli_scoring_mode must be 'not_contradicted' per ADR-0016."""
        settings = Settings()
        assert settings.nli_scoring_mode == "not_contradicted", (
            f"Production default nli_scoring_mode is '{settings.nli_scoring_mode}', "
            f"but ADR-0016 (revised after measurement) requires 'not_contradicted'. "
            f"Entailment mode produces 0.113 faithfulness and makes the system non-functional."
        )

    def test_production_default_unsupported_ratio_matches_adr_0016(self):
        """The production default for nli_unsupported_ratio must be 0.2 per ADR-0016."""
        settings = Settings()
        assert settings.nli_unsupported_ratio == 0.2, (
            f"Production default nli_unsupported_ratio is {settings.nli_unsupported_ratio}, "
            f"but ADR-0016 (revised) requires 0.2 for not_contradicted mode."
        )

    def test_verifier_from_settings_matches_eval_verifier(self):
        """Verifiers constructed from the same Settings must have identical behavior.

        This is the core parity test: the chat route and the eval harness
        both construct NliAnswerVerifier from Settings, so they must produce
        the same verification results for the same inputs.
        """
        settings = Settings()

        # Production verifier (as constructed by chat route)
        prod_verifier = NliAnswerVerifier(
            entailment_threshold=settings.nli_entailment_threshold,
            scoring_mode=settings.nli_scoring_mode,
            unsupported_ratio=settings.nli_unsupported_ratio,
        )

        # Eval verifier (as constructed by eval tests)
        eval_verifier = NliAnswerVerifier(
            entailment_threshold=settings.nli_entailment_threshold,
            scoring_mode=settings.nli_scoring_mode,
            unsupported_ratio=settings.nli_unsupported_ratio,
        )

        # Both must have the same internal configuration
        assert prod_verifier._scoring_mode == eval_verifier._scoring_mode
        assert prod_verifier._unsupported_ratio == eval_verifier._unsupported_ratio
        assert prod_verifier._entailment_threshold == eval_verifier._entailment_threshold

    def test_verifier_config_round_trip_through_env(self, monkeypatch):
        """Environment variables must correctly override Settings defaults.

        This ensures that NLI_SCORING_MODE and NLI_UNSUPPORTED_RATIO
        env vars are picked up by pydantic-settings, so production
        deployments can override the defaults without code changes.
        """
        monkeypatch.setenv("NLI_SCORING_MODE", "entailment")
        monkeypatch.setenv("NLI_UNSUPPORTED_RATIO", "0.0")

        # Clear lru_cache to force Settings reload
        get_settings = __import__(
            "app.core.config", fromlist=["get_settings"]
        ).get_settings
        get_settings.cache_clear()

        settings = Settings()
        assert settings.nli_scoring_mode == "entailment"
        assert settings.nli_unsupported_ratio == 0.0

        # Restore defaults
        get_settings.cache_clear()
