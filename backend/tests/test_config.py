"""Tests for configuration settings."""

from app.core.config import Settings


def test_default_settings() -> None:
    test_settings = Settings(PROJECT_NAME="StudyMindTest")
    assert test_settings.PROJECT_NAME == "StudyMindTest"
    assert test_settings.MIN_RELEVANCE_SCORE == 0.35
    assert test_settings.EMBEDDING_DIMENSION == 1024
    assert test_settings.ENABLE_OUTSIDE_KNOWLEDGE is False


def test_thresholds_configuration() -> None:
    custom = Settings(
        MIN_RELEVANCE_SCORE=0.45,
        RETRIEVAL_TOP_K=40,
        RERANK_TOP_N=8,
    )
    assert custom.MIN_RELEVANCE_SCORE == 0.45
    assert custom.RETRIEVAL_TOP_K == 40
    assert custom.RERANK_TOP_N == 8
