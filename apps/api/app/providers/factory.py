from __future__ import annotations

import logging

from app.config import Settings
from app.memory.llm_extractor import FakeExtractionProvider, LLMExtractionProvider
from app.memory.summarizer_provider import LLMSummarizerProvider, RuleSummarizerProvider
from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.providers.judge import NoopJudgeProvider
from app.providers.registry import ProviderRegistry
from app.runtime.repository import EMBED_DIM

logger = logging.getLogger(__name__)


def deterministic_provider_registry(*, embedding_dim: int = 256) -> ProviderRegistry:
    """Build the no-network provider registry used by tests/benchmarks/defaults."""
    registry = ProviderRegistry()
    embedding = DeterministicHashEmbeddingProvider(dim=embedding_dim)
    registry.register(ProviderKind.embedding, embedding, embedding.capabilities)
    summarizer = RuleSummarizerProvider()
    registry.register(ProviderKind.summarizer, summarizer, _rule_summarizer_capabilities())
    judge = NoopJudgeProvider()
    registry.register(ProviderKind.judge, judge, judge.capabilities)
    return registry


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    """Build providers from settings without leaking secrets into snapshots."""
    registry = ProviderRegistry()
    extraction, extraction_capabilities = _build_extraction_provider(settings)
    if extraction is not None and extraction_capabilities is not None:
        registry.register(ProviderKind.extraction, extraction, extraction_capabilities)
    embedding = _build_embedding_provider(settings)
    registry.register(ProviderKind.embedding, embedding, embedding.capabilities)
    summarizer, summarizer_capabilities = _build_summarizer_provider(settings)
    registry.register(ProviderKind.summarizer, summarizer, summarizer_capabilities)
    judge = NoopJudgeProvider()
    registry.register(ProviderKind.judge, judge, judge.capabilities)
    return registry


def _build_extraction_provider(settings: Settings) -> tuple[FakeExtractionProvider | LLMExtractionProvider | None, ProviderCapabilities | None]:
    if not settings.llm_extraction_enabled:
        return None, None
    if settings.llm_api_key:
        provider = LLMExtractionProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_ms / 1000,
            max_tokens=settings.llm_max_tokens,
            use_json_response_format=settings.llm_use_json_response_format,
        )
        return provider, ProviderCapabilities(
            provider_id="extraction.openai_compatible.v1",
            kind=ProviderKind.extraction,
            deterministic=False,
            requires_network=True,
            endpoint_types=("openai_chat_completions",),
            model=settings.llm_model,
            metadata={"base_url_host": _host_label(settings.llm_base_url)},
        )
    logger.warning(
        "MEMTRACE_LLM_EXTRACTION_ENABLED is set but MEMTRACE_LLM_API_KEY is empty; "
        "using deterministic FakeExtractionProvider."
    )
    provider = FakeExtractionProvider()
    return provider, ProviderCapabilities(
        provider_id="extraction.fake_writer.v1",
        kind=ProviderKind.extraction,
        deterministic=True,
        requires_network=False,
        configured=False,
    )


def _build_embedding_provider(settings: Settings) -> DeterministicHashEmbeddingProvider | OpenAIEmbeddingProvider:
    provider_name = settings.embedding_provider.strip().lower().replace("-", "_")
    if settings.embedding_dim != EMBED_DIM:
        logger.warning(
            "MEMTRACE_EMBEDDING_DIM=%s does not match fixed pgvector dimension %s; using %s.",
            settings.embedding_dim,
            EMBED_DIM,
            EMBED_DIM,
        )
    if provider_name in {"openai", "openai_compatible"}:
        if settings.embedding_api_key:
            return OpenAIEmbeddingProvider(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                model=settings.embedding_model,
                dimensions=EMBED_DIM,
                timeout_s=settings.embedding_timeout_ms / 1000,
            )
        logger.warning(
            "MEMTRACE_EMBEDDING_PROVIDER=%s requires MEMTRACE_EMBEDDING_API_KEY; "
            "using deterministic hash embedding provider.",
            settings.embedding_provider,
        )
        return DeterministicHashEmbeddingProvider(
            dim=EMBED_DIM,
            configured=False,
            fallback_provider_id="embedding.deterministic_hash.v1",
        )
    return DeterministicHashEmbeddingProvider(dim=EMBED_DIM)


def _build_summarizer_provider(settings: Settings) -> tuple[RuleSummarizerProvider | LLMSummarizerProvider, ProviderCapabilities]:
    if settings.llm_summarizer_enabled:
        if settings.llm_api_key:
            provider = LLMSummarizerProvider(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_s=settings.compaction_timeout_ms / 1000,
                max_tokens=settings.llm_max_tokens,
                use_json_response_format=settings.llm_use_json_response_format,
            )
            return provider, provider.capabilities
        logger.warning(
            "MEMTRACE_LLM_SUMMARIZER_ENABLED is set but MEMTRACE_LLM_API_KEY is empty; "
            "using deterministic RuleSummarizerProvider."
        )
    return RuleSummarizerProvider(), _rule_summarizer_capabilities()


def _rule_summarizer_capabilities() -> ProviderCapabilities:
    return RuleSummarizerProvider.capabilities


def _host_label(base_url: str) -> str:
    try:
        import httpx

        return httpx.URL(base_url).host or "unknown"
    except Exception:
        return "unknown"
