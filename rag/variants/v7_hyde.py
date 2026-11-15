"""V7 (query): retrieve with a hypothetical ideal proposal for the job (HyDE). Targets vague client posts."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v7_hyde", query="hyde", retrieval="hybrid", description="HyDE")
