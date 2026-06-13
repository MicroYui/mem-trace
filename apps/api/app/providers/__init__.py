from app.providers.base import EmbeddingProvider, ProviderCapabilities, ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.providers.judge import JudgeProvider, NoopJudgeProvider
from app.providers.registry import ProviderRegistry


def __getattr__(name: str):
    if name in {"build_provider_registry", "deterministic_provider_registry"}:
        from app.providers.factory import build_provider_registry, deterministic_provider_registry

        return {
            "build_provider_registry": build_provider_registry,
            "deterministic_provider_registry": deterministic_provider_registry,
        }[name]
    raise AttributeError(name)

__all__ = [
    "DeterministicHashEmbeddingProvider",
    "EmbeddingProvider",
    "JudgeProvider",
    "NoopJudgeProvider",
    "OpenAIEmbeddingProvider",
    "ProviderCapabilities",
    "ProviderKind",
    "ProviderRegistry",
    "build_provider_registry",
    "deterministic_provider_registry",
]
