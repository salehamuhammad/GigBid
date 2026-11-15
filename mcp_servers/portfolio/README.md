# gigbid-portfolio-mcp

A read-only MCP server that lets any MCP host (Claude Desktop, Cursor, the MCP Inspector, your own
agent) search a freelancer's portfolio for **evidence** before claiming experience: case studies,
repositories (README and code), client reviews, a CV and past proposals with their outcomes.

It answers "have I actually done this?" with ranked items and their dates, sources and outcomes,
and says so plainly (`refused: true`) when nothing in the portfolio proves a requirement.

## Tools, resources, prompts

| Kind | Name | What it does |
|---|---|---|
| tool | `search_evidence(requirement, k, filters)` | Ranked evidence for one requirement. Filters: types, skills, client industry, outcome, date. `refused=true` means do not claim it. |
| tool | `get_case_study(id)` | One full item, including code for repositories. |
| tool | `list_skills()` | Every skill the portfolio can prove and how many items back it. |
| resource | `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://index` | Items as Markdown. |
| prompt | `answer_screening_question`, `draft_grounded_proposal`, `do_i_have_experience` | Ready-made workflows. |

All tools are annotated `readOnlyHint: true`. The default retrieval uses the V9 skill graph with
requirement decomposition. GigBid's bid graph checks evidence coverage and verifies draft claims.

## Install and run

```bash
# from a clone of the GigBid repository
pip install -e ".[models]"            # [models] adds the open-weight embedding and reranker models
python -m scripts.generate_data        # the bundled synthetic sample portfolios

gigbid-portfolio-mcp --owner ai_engineer                         # stdio
gigbid-portfolio-mcp --owner ai_engineer --transport http --port 8101   # Streamable HTTP (needs a bearer token)
```

With `uvx` (no install, straight from the repository):

```bash
uvx --from "git+https://github.com/<you>/gigbid" gigbid-portfolio-mcp --owner ai_engineer
```

With Docker:

```bash
docker build -f infra/docker/api.Dockerfile -t gigbid .
docker run -i --rm gigbid python -m mcp_servers.portfolio.server --owner ai_engineer
```

### Claude Desktop

```json
{ "mcpServers": { "portfolio": { "command": "gigbid-portfolio-mcp", "args": ["--owner", "ai_engineer"] } } }
```

### Your own portfolio

Make a folder `my-data/personas/me/` with any of: `cv.md` or `cv.pdf`, `case_studies/*.md`,
`reviews/*.md`, `proposals/*.md`, `repos/<name>/README.md` plus source files. Front matter is
optional (`title`, `skills`, `date`, `client_industry`, `outcome`); skills are detected from the
text when missing. Then:

```bash
gigbid-portfolio-mcp --owner me --data-dir ./my-data
```

The first call builds the index; the embedding cache makes later rebuilds incremental.
