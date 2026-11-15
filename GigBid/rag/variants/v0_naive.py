"""V0 (baseline, required): fixed chunks, top-k cosine on the whole job post. The number everything else must beat."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v0_naive", description="Naive dense: fixed chunks, top-k cosine on the whole post")
