"""V9 (agentic): skill graph. Skills, projects, industries and outcomes as a graph; answers 'have I done X for a client in Y industry?'."""
from rag.retriever import VariantConfig

CONFIG = VariantConfig(name="v9_skill_graph", query="decompose", retrieval="graph", description="Skill graph (GraphRAG)")
