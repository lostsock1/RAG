from app.services.embedders.base import Embedder
from app.services.embedders.stub import StubEmbedder

__all__ = ["BgeM3Embedder", "Embedder", "StubEmbedder"]

# Lazy import — FlagEmbedding is an optional dependency
def __getattr__(name: str):
    if name == "BgeM3Embedder":
        from app.services.embedders.bge_m3 import BgeM3Embedder
        return BgeM3Embedder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
