"""Portfolio MCP server through an in-memory MCP client (A7)."""
import pytest

from agent.mcp_client import ToolError


async def test_search_evidence_returns_typed_items(toolbox):
    r = await toolbox.call("matcher", "portfolio.search_evidence", {"requirement": "RAG chatbot with FAISS vector search and FastAPI", "k": 5})
    assert 1 <= len(r["evidence"]) <= 5
    e = r["evidence"][0]
    assert {"id", "type", "source", "date", "outcome", "snippet", "score"} <= set(e)
    assert any("RAG" in x["skills"] or "FAISS" in x["skills"] for x in r["evidence"])


async def test_filters_and_get_case_study(toolbox):
    r = await toolbox.call("matcher", "portfolio.search_evidence", {"requirement": "FastAPI service", "k": 5, "filters": {"types": ["repo"]}})
    assert r["evidence"] and all(e["type"] == "repo" for e in r["evidence"])
    full = await toolbox.call("writer", "portfolio.get_case_study", {"id": r["evidence"][0]["id"]})
    assert full["code"] and full["skills"]


async def test_unknown_id_is_a_tool_error(toolbox):
    with pytest.raises(ToolError):
        await toolbox.call("writer", "portfolio.get_case_study", {"id": "does-not-exist"})


async def test_list_skills(toolbox):
    r = await toolbox.call("matcher", "portfolio.list_skills", {})
    assert r["total_items"] > 100 and any(s["skill"] == "RAG" for s in r["skills"])


async def test_resources_and_prompts(toolbox):
    async with toolbox.session("portfolio") as s:
        templates = {t.uriTemplate for t in (await s.list_resource_templates()).resourceTemplates}
        assert {"portfolio://case/{id}", "portfolio://proposal/{id}"} <= templates
        res = await s.read_resource("portfolio://case/ai_engineer-case-001")
        assert "Support knowledge assistant" in res.contents[0].text
        prompts = {p.name for p in (await s.list_prompts()).prompts}
        assert "answer_screening_question" in prompts
        p = await s.get_prompt("answer_screening_question", {"question": "Have you used FAISS?"})
        assert "FAISS" in p.messages[0].content.text
