"""V3 (retrieval, required): cross-encoder reranking of the first-stage pool. Targets precision at small k."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v3_rerank", retrieval="hybrid", rerank=True, description="Hybrid + cross-encoder rerank")
