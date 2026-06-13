from __future__ import annotations

from app.config import Settings
from app.memory.llm_extractor import FakeExtractionProvider, LLMExtractionProvider
from app.memory.summarizer_provider import LLMSummarizerProvider, RuleSummarizerProvider
from app.providers.base import ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.providers.factory import build_provider_registry, deterministic_provider_registry
from app.providers.judge import NoopJudgeProvider


def test_deterministic_provider_registry_registers_retrieval_and_judge_families():
    registry = deterministic_provider_registry(embedding_dim=256)

    assert isinstance(registry.get(ProviderKind.embedding), DeterministicHashEmbeddingProvider)
    assert isinstance(registry.get(ProviderKind.judge), NoopJudgeProvider)
    snapshot = registry.snapshot()
    assert snapshot["embedding"]["provider_id"] == "embedding.deterministic_hash.v1"
    assert snapshot["embedding"]["metadata"] == {"algorithm": "blake2b_hash_bow", "dim": 256}
    assert snapshot["judge"]["provider_id"] == "judge.noop.v1"
    assert snapshot["summarizer"]["provider_id"] == "summarizer.rule.v1"


def test_build_provider_registry_uses_openai_embedding_when_explicitly_configured():
    settings = Settings(
        embedding_provider="openai",
        embedding_api_key="sk-test-secret",
        embedding_base_url="https://embeddings.example.test/v1",
        embedding_model="text-embedding-3-small",
        embedding_dim=256,
    )

    registry = build_provider_registry(settings)

    assert isinstance(registry.get(ProviderKind.embedding), OpenAIEmbeddingProvider)
    snapshot = registry.snapshot()
    assert snapshot["embedding"]["provider_id"] == "embedding.openai_compatible.v1"
    assert snapshot["embedding"]["model"] == "text-embedding-3-small"
    assert snapshot["embedding"]["metadata"] == {"base_url_host": "embeddings.example.test", "dim": 256}
    assert "sk-test-secret" not in str(snapshot)
    assert snapshot["judge"]["provider_id"] == "judge.noop.v1"


def test_build_provider_registry_keeps_embedding_dimension_pgvector_compatible():
    settings = Settings(
        embedding_provider="openai",
        embedding_api_key="sk-test-secret",
        embedding_dim=128,
    )

    registry = build_provider_registry(settings)

    snapshot = registry.snapshot()
    assert snapshot["embedding"]["metadata"]["dim"] == 256


def test_build_provider_registry_preserves_extraction_provider_wiring():
    fake_registry = build_provider_registry(Settings(llm_extraction_enabled=True, llm_api_key=""))
    real_registry = build_provider_registry(Settings(llm_extraction_enabled=True, llm_api_key="sk-llm-secret"))

    assert isinstance(fake_registry.get(ProviderKind.extraction), FakeExtractionProvider)
    assert fake_registry.snapshot()["extraction"]["provider_id"] == "extraction.fake_writer.v1"
    assert isinstance(real_registry.get(ProviderKind.extraction), LLMExtractionProvider)
    assert real_registry.snapshot()["extraction"]["provider_id"] == "extraction.openai_compatible.v1"
    assert "sk-llm-secret" not in str(real_registry.snapshot())


def test_build_provider_registry_wires_configured_llm_summarizer_without_secrets():
    registry = build_provider_registry(Settings(llm_summarizer_enabled=True, llm_api_key="sk-llm-secret"))

    assert isinstance(registry.get(ProviderKind.summarizer), LLMSummarizerProvider)
    snapshot = registry.snapshot()
    assert snapshot["summarizer"]["provider_id"] == "summarizer.openai_compatible.v1"
    assert snapshot["summarizer"]["requires_network"] is True
    assert "sk-llm-secret" not in str(snapshot)


def test_build_provider_registry_degrades_llm_summarizer_without_key():
    registry = build_provider_registry(Settings(llm_summarizer_enabled=True, llm_api_key=""))

    assert isinstance(registry.get(ProviderKind.summarizer), RuleSummarizerProvider)
    snapshot = registry.snapshot()
    assert snapshot["summarizer"]["provider_id"] == "summarizer.rule.v1"
    assert snapshot["summarizer"]["deterministic"] is True


def test_summarizer_provider_instances_expose_capabilities_for_runtime_overrides():
    rule = RuleSummarizerProvider()
    llm = LLMSummarizerProvider(
        api_key="sk-llm-secret",
        base_url="https://llm.example.test/v1",
        model="gpt-test",
    )

    assert rule.capabilities.snapshot()["provider_id"] == "summarizer.rule.v1"
    llm_snapshot = llm.capabilities.snapshot()
    assert llm_snapshot["provider_id"] == "summarizer.openai_compatible.v1"
    assert llm_snapshot["model"] == "gpt-test"
    assert llm_snapshot["fallback_provider_id"] == "summarizer.rule.v1"
    assert llm_snapshot["metadata"] == {"base_url_host": "llm.example.test"}
    assert "sk-llm-secret" not in str(llm_snapshot)


def test_build_provider_registry_marks_embedding_fallback_when_openai_key_missing():
    registry = build_provider_registry(Settings(embedding_provider="openai", embedding_api_key=""))

    snapshot = registry.snapshot()
    assert isinstance(registry.get(ProviderKind.embedding), DeterministicHashEmbeddingProvider)
    assert snapshot["embedding"]["provider_id"] == "embedding.deterministic_hash.v1"
    assert snapshot["embedding"]["configured"] is False
    assert snapshot["embedding"]["fallback_provider_id"] == "embedding.deterministic_hash.v1"


def test_build_provider_registry_deterministic_fallback_uses_pgvector_dimension():
    registry = build_provider_registry(Settings(embedding_provider="deterministic", embedding_dim=128))

    snapshot = registry.snapshot()
    assert snapshot["embedding"]["metadata"]["dim"] == 256
