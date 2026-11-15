"""V5 (indexing): summary, README and code are indexed as separate vectors and returned as one item. Targets repos that look irrelevant from their README alone."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v5_multivector", index="multivector", retrieval="hybrid", description="Multi-vector items")
