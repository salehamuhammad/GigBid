"""V1 (query, required): one retrieval per extracted requirement, then reciprocal-rank merge. Targets jobs that ask for five different things."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v1_decompose", query="decompose", description="Requirement decomposition")
