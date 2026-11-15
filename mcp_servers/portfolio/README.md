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

With Docker:

```bash
git clone https://github.com/salehamuhammad/GigBid.git
cd GigBid
docker build -f infra/docker/api.Dockerfile -t gigbid .
docker run -i --rm -e MODEL_PROFILE=offline gigbid python -m mcp_servers.portfolio.server --owner ai_engineer
```

The Docker build generates the bundled synthetic portfolios. The command starts a stdio MCP
server for a host such as Claude Desktop or Cursor. The offline profile needs no provider key.
For BGE embeddings, set `MODEL_PROFILE=open` and provide the configured model-provider
environment privately. The real embedding dependencies are included in the Docker image.

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
GIGBID_DATA_DIR=./my-data gigbid-portfolio-mcp --owner me
```

The first call builds the index; the embedding cache makes later rebuilds incremental.
