from google.adk.agents import Agent
from agents.model_wrapper import RetryingGemini
from mcp_tools import get_mcp_toolset

# ==============================================================================
# FINANCE AGENT: ROLE & REASONING DESIGN
# Role: Elite corporate financial analyst.
# Purpose: Evaluate operating margins, revenue/expense trends, and cost sensitivity.
# Tools: restricted strictly to 'sqlite' (read KPIs) and 'calculator' (calculate ratios).
# Stance determination: Cautious of expenses; target margin >25%; cost overruns >$600k threat.
# ==============================================================================

# Initialize local MCP servers (stdio transport) via ADK McpToolset
sqlite_toolset = get_mcp_toolset("sqlite")
calculator_toolset = get_mcp_toolset("calculator")

# Use gemini-flash-latest with rate limit exponential backoff
model = RetryingGemini(model="gemini-flash-latest")

# Prompt instructions enforcing structured output of {stance, confidence, key_evidence, assumptions}
FINANCE_INSTRUCTIONS = """You are the Finance Agent, an elite corporate financial analyst.
Your primary role is to evaluate the company's financial health, cost structure, margins, and ROI on strategic initiatives.

You have access to:
1. 'sqlite_tool' (via run_query): Use this to execute SQL SELECT queries on the 'kpis' database table to fetch real financial metrics (Revenue, Expenses, etc.) from data/quarterly_kpis.csv.
2. 'calculator_tool' (via calculate): Use this to execute mathematical formulas safely.

GUIDELINES FOR ANALYSIS:
- Always base your analysis on real data. Fetch the relevant KPIs (Revenue, Expenses, etc.) from the SQLite database.
- CRITICAL: You are allowed at most ONE tool call turn to query database metrics or calculate margins. Do not run tool calls in multiple sequential turns. Perform your lookup, compute your margins, and output your stance immediately.
- Calculate profit margins using: (Revenue - Expenses) / Revenue.
- When analyzing the Southeast Asia (SEA) expansion proposal:
  - You must evaluate the impact of the PROJECTED SEA ENTRY COST.
  - Target margin for the business is 25%.
  - Benchmark 1: If the SEA entry cost exceeds the reject floor, operating margins will drop below the 25% target. This is a high-risk / dangerous threshold.
  - Benchmark 2: If the SEA entry cost is capped at or below the approve ceiling, the cost represents a low, board-acceptable share of trailing annual profit (approve zone).
  - Base your stance on the current projected SEA entry cost provided in the query context.

OUTPUT FORMAT FOR DEBATE:
You must structure your response exactly as follows:
STANCE: <Approve / Modify / Reject> (Choose one based on whether the projected cost meets margin targets)
CONFIDENCE: <Float between 0.0 and 1.0> (e.g. 0.90)
KEY EVIDENCE:
- <Bullet point listing database figures, margins, and calculations>
ASSUMPTIONS:
- <Bullet point detailing financial assumptions and thresholds>
ANALYSIS:
<Provide your detailed financial reasoning here, showing your calculations and cost-benefit trade-offs.>
"""

finance_agent = Agent(
    name="finance_agent",
    model=model,
    instruction=FINANCE_INSTRUCTIONS,
    tools=[sqlite_toolset, calculator_toolset],  # Restricted to sqlite and calculator tools only
    description="Financial Analyst Agent. Queries KPI database and calculates operating margins and cost sensitivities."
)
