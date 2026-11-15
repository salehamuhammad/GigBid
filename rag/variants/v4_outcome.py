"""V4 (ranking): outcome-aware ranking. Evidence from projects cited in won/replied proposals is boosted, and winning past proposals are returned as phrasing examples (never as proof)."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v4_outcome", retrieval="hybrid", outcome_boost=True, description="Outcome-aware ranking")
