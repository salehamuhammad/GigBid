"""V2 (retrieval, required): BM25 + dense with reciprocal rank fusion. Targets exact tool names (Celery, dbt, Pinecone) that embeddings blur."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v2_hybrid", retrieval="hybrid", description="Hybrid BM25 + dense with RRF")
