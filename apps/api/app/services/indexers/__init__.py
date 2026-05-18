from app.services.indexers.base import LexicalIndexer, VectorIndexer
from app.services.indexers.stub import StubLexicalIndexer, StubVectorIndexer

__all__ = [
    "LexicalIndexer",
    "OpenSearchLexicalIndexer",
    "QdrantVectorIndexer",
    "StubLexicalIndexer",
    "StubVectorIndexer",
    "VectorIndexer",
]

# Lazy imports — qdrant-client and opensearch-py are optional dependencies
def __getattr__(name: str):
    if name == "QdrantVectorIndexer":
        from app.services.indexers.qdrant_indexer import QdrantVectorIndexer
        return QdrantVectorIndexer
    if name == "OpenSearchLexicalIndexer":
        from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer
        return OpenSearchLexicalIndexer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
