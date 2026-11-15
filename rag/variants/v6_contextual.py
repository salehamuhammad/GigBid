"""V6 (indexing): a generated context line is prepended to every chunk. Targets fragments that lose meaning out of context."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v6_contextual", index="contextual", retrieval="hybrid", description="Contextual retrieval")
