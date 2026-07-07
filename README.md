# CouncilAI: Explainable Multi-Agent Business Decision Intelligence System

Built with Google's ADK (Agent Development Kit), CouncilAI is a business decision intelligence framework designed to evaluate strategic initiatives (such as regional market expansions) by facilitating a structured, explainable 2-round deliberation between specialized agents.

## Project Structure

```
CouncilAI/
├── agents/
│   ├── coordinator.py             # custom BaseAgent managing the 2-round deliberation
│   ├── finance_agent.py           # evaluates financial margins and cost sensitivities
│   ├── marketing_agent.py         # evaluates LTV, CAC, and growth front-loading
│   ├── risk_agent.py              # evaluates compliance delays and capital exposures
│   └── model_wrapper.py           # retries model calls with exponential backoff on 429/503 errors
├── mcp_tools/
│   ├── calculator_tool.py         # local FastMCP server for safe AST-based math
│   ├── sqlite_tool.py             # local FastMCP server for read-only database query execution (accepts custom db_path)
│   ├── filesystem_tool.py         # local FastMCP server for workspace directory listing & reading
│   └── pdf_tool.py                # local FastMCP server for PDF text extraction (pypdf, accepts custom pdf_path)
├── security/
│   ├── audit_log.py               # logs transactions in JSON Lines format to data/audit.log
│   ├── permissions.py             # role-based agent-to-tool execution verification
│   └── input_guard.py             # sanitizes inputs against prompt and SQL injections
├── ui/
│   └── app.py                     # Streamlit dashboard interface organized into tabs
├── data/                          # holds generated KPIs, SQLite DB, and PDF reports
├── generate_mock_data.py          # bootstraps data/ files
└── pyproject.toml                 # project metadata and dependencies
```

## Setup & Running Instructions

### 1. Requirements
Ensure you have `uv` installed. If not, refer to the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your Gemini API key:
```bash
cp .env.example .env
```
Open `.env` and populate:
```ini
GEMINI_API_KEY=AIzaSy...
```

### 3. Bootstrap Business Data
Sync virtual environment dependencies and run the bootstrap script to generate the KPI dataset, the business report PDF, and initialize the SQLite database:
```bash
uv sync
uv run python generate_mock_data.py
```

### 4. Run the Streamlit Application
Start the Streamlit dashboard in your local web browser:
```bash
uv run streamlit run ui/app.py
```

## Security & Architecture Details

1. **Local MCP Servers**: Every tool in `/mcp_tools` is written as a Model Context Protocol server using FastMCP and executed dynamically over stdio transport.
2. **2-Round Deliberation**:
   - **Round 1 (Specialist Analysis)**: Finance, Marketing, and Risk agents run independently with isolated session histories. Each agent calls its real assigned local MCP tools to read data and returns `{stance, confidence, key_evidence, assumptions}`.
   - **Round 2 (Synthesis)**: The lead `coordinator_synthesis` agent is invoked once, receives the raw Round 1 outputs of all three specialists, and compiles the final Executive Decision Report.
3. **Tool Output Caching**: To minimize Gemini API key usage and cost, a tool-response cache is maintained inside the custom security plugin. Repeated identical database queries or PDF page reads across agents or simulation runs are resolved instantly from the cache.
4. **Dry Run Simulation Mode**: An optional "Dry Run" checkbox in the sidebar allows you to run simulations instantly. The security plugin intercepts model calls and returns highly realistic mock responses keyed on cost and agent type, bypassing live Gemini API calls entirely for UI demo testing.
5. **Session-Specific File Uploads**: Users can upload custom KPI CSVs (validating against the schema) and report PDFs directly in the "Data & Security Logs" tab. The system saves these files with unique session suffixes and programmatically compiles uploaded CSVs into custom SQLite DB instances. The coordinator injects these session-specific file paths directly into the agents' instructions to re-route their tool calls dynamically.
6. **ADK Security Plugin**: Centrally validates input prompts (Input Guard), verifies tool execution permissions per agent (Permissions), and logs transactions to `data/audit.log` (Audit Log).
7. **429 Rate Limiter**: Automatically intercepts and retries Gemini API calls with exponential backoff (1s, 2s, 4s, 8s) if a `RESOURCE_EXHAUSTED` or `UNAVAILABLE` limit is encountered.
8. **Deterministic Cost-Tier Policy**: Cost-tier thresholds (Approve ceiling, Phased launch ceiling, Reject floor) are calculated locally in Python before any agent is invoked, using a trailing financial data formula. The boundaries and policy bucket classifications are passed to the agents as stated facts, ensuring 100% deterministic stances that are identical across repeated runs on the same data.

## Dynamic vs. Fixed Dimensions

| Dynamic Dimensions (Adapts per dataset) | Fixed Dimensions (Architectural Constants) |
| :--- | :--- |
| **Region & Target Market**: Parsed dynamically from qualitative PDF report context. | **CSV Schema Requirement**: Strict columns required for database compiling (`Quarter`, `Revenue`, `Expenses`, etc.). |
| **Company & Initiative Name**: Extracted from loaded document texts. | **Margin Floor Policy**: 25% minimum target operating margin policy threshold. |
| **Baseline Entry Cost**: Retrieved directly from stated PDF text. | **Approve Multiplier**: 15% (0.15) of annual trailing operating profit for low-risk Approve zone. |
| **KPI Metrics & Trends**: Loaded from uploaded CSV sheets (LTV, CAC, Risk Score, Marketing Spend, Compliance Status). | **Agent Roles & Toolsets**: RBAC assignments (Finance has SQLite/Calc, Marketing has PDF/Filesystem, etc.). |
| **Cost-Tier Thresholds**: Boundaries derived dynamically from the CSV trailing numbers. | **Debate Structure**: Genuine 2-Round sequential debate with 2.5s delay and 3-minute safeguard timeout. |
| **Interactive Dashboard Charts**: Redraws line and bar plots based on loaded CSV periods. | **Security Rules**: Prompt injection sanitization, DB access restriction, and synthesizer least privilege. |


