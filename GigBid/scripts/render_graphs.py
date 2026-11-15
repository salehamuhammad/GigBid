"""Render both graphs from code (C: "both graphs rendered from code") to docs/graphs/*.mmd and an HTML viewer."""
from pathlib import Path

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph

out = Path(__file__).resolve().parents[1] / "docs" / "graphs"
out.mkdir(parents=True, exist_ok=True)
html = ["<!doctype html><html><head><meta charset='utf-8'><title>GigBid graphs</title><script type='module'>import m from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';m.initialize({startOnLoad:true});</script></head><body>"]
for name, g in (("bid_graph", build_bid_graph()), ("conversation_graph", build_conversation_graph())):
    mmd = g.get_graph().draw_mermaid()
    (out / f"{name}.mmd").write_text(mmd)
    html.append(f"<h2>{name}</h2><pre class='mermaid'>{mmd}</pre>")
    print("wrote", out / f"{name}.mmd")
(out / "graphs.html").write_text("\n".join(html) + "</body></html>")
