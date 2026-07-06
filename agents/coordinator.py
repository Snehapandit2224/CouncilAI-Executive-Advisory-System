import logging
import asyncio
import re
import json
from typing import AsyncGenerator
from google.adk.agents import BaseAgent, Agent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

# Import specialist agents
from agents.finance_agent import finance_agent
from agents.marketing_agent import marketing_agent
from agents.risk_agent import risk_agent
from agents.model_wrapper import RetryingGemini

# Import security modules
from security.audit_log import log_event
from security.permissions import check_permission
from security.input_guard import validate_input

class SecurityBlockException(Exception):
    """Exception raised when a safety guardrail blocks a prompt."""
    pass

class AgentIterationLimitExceeded(Exception):
    """Exception raised when an agent exceeds its internal loop steps."""
    pass

def get_cost_tiers(ltm_revenue, ltm_expenses, quarterly_operating_profit, margin_floor=0.25):
    """Calculates deterministic cost-tier thresholds from trailing financial data."""
    ttm_operating_profit = ltm_revenue - ltm_expenses
    approve_ceiling = 0.15 * ttm_operating_profit          # ~15% of annual profit
    phased_ceiling = quarterly_operating_profit             # one quarter's profit
    reject_floor = (ltm_revenue * (1 - margin_floor)) - ltm_expenses  # margin-floor breach point
    return approve_ceiling, phased_ceiling, reject_floor

def is_valid_tool_response(response) -> bool:
    """Checks if a tool output response is valid and non-empty."""
    if response is None:
        return False
    if isinstance(response, dict):
        if not response:
            return False
        if response.get("status") == "error":
            return False
        if any(str(v).lower().startswith("error") for v in response.values()):
            return False
    if isinstance(response, str):
        res_str = response.strip()
        if not res_str or res_str == "{}" or res_str.lower().startswith("error"):
            return False
    return True

logger = logging.getLogger("councilai.coordinator")

# ==============================================================================
# EVENT HELPER FUNCTION
# Utility to construct Event objects with correct Pydantic/GenAI content schemas.
# Avoids plain strings in Event.content by packaging them in types.Content wrappers.
# ==============================================================================
def make_event(author: str, text: str) -> Event:
    """Helper to safely construct an Event with type-annotated Content objects."""
    role = "user" if author.strip().lower() == "user" else "model"
    part = types.Part.from_text(text=text)
    content = types.Content(role=role, parts=[part])
    return Event(author=author, content=content)

# Initialize helper coordinator_synthesis agent for Round 2 (synthesis)
coordinator_synthesis_agent = Agent(
    name="coordinator_synthesis",
    model=RetryingGemini(model="gemini-flash-latest"),
    instruction="""You are the Lead Executive Coordinator.
Your task is to review the Round 1 analyses from the Finance, Marketing, and Risk agents, and produce a unified, explainable Executive Decision Report.
Analyze their points, calculate a confidence-weighted decision score (tallying stances), highlight their disagreements and consensus, and output the report in the requested layout.
""",
    description="Compiles and synthesizes multi-agent debate history into the final executive report."
)

# ==============================================================================
# SECURITY AUDIT & DEBATE CACHING PLUGIN
# Intercepts ADK lifecycle hooks globally to perform guardrail validation,
# check tool execution permissions, cache tool output, and mock dry runs.
# ==============================================================================
class SecurityAuditPlugin(BasePlugin):
    """Custom ADK Plugin that intercepts all model calls and tool executions
    to run safety checks, check permissions, handle caching, and mock dry runs.
    """
    def __init__(self, name: str = "security_audit"):
        super().__init__(name=name)
        self.agent_step_counts = {}

    async def before_agent_callback(self, **kwargs) -> None:
        callback_context = kwargs.get("callback_context")
        if not callback_context:
            return
        
        # Initialize step counter for this invocation turn
        self.agent_step_counts[callback_context.invocation_id] = 0
        
        callback_context.state["active_agent"] = callback_context.agent_name
        log_event(
            event_type="AGENT_RUN",
            actor=callback_context.agent_name,
            action="started",
            status="SUCCESS",
            details={"invocation_id": callback_context.invocation_id}
        )

    async def after_agent_callback(self, **kwargs) -> types.Content | None:
        callback_context = kwargs.get("callback_context")
        if callback_context:
            self.agent_step_counts.pop(callback_context.invocation_id, None)
            log_event(
                event_type="AGENT_RUN",
                actor=callback_context.agent_name,
                action="completed",
                status="SUCCESS",
                details={"invocation_id": callback_context.invocation_id}
            )
        return None

    async def before_model_callback(self, **kwargs) -> LlmResponse | None:
        callback_context = kwargs.get("callback_context")
        llm_request = kwargs.get("llm_request")
        if not callback_context or not llm_request:
            return None

        # Check and enforce hard max iteration limit
        inv_id = callback_context.invocation_id
        current_steps = self.agent_step_counts.get(inv_id, 0) + 1
        self.agent_step_counts[inv_id] = current_steps
        if current_steps > 5:
            raise AgentIterationLimitExceeded(
                f"Agent '{callback_context.agent_name}' was aborted because it exceeded the maximum limit of "
                f"5 internal model/tool iterations per turn."
            )

        # Extract prompt input text for validation
        prompt_text = ""
        if llm_request.contents:
            for content in llm_request.contents:
                if content.parts:
                    for part in content.parts:
                        if part.text:
                            prompt_text += part.text + " "

        # 1. Run Input Guard Safety check
        is_safe, error_msg = validate_input(prompt_text)
        if not is_safe:
            log_event(
                event_type="SECURITY_BLOCK",
                actor=callback_context.agent_name or "system",
                action="prompt_validation",
                status="BLOCKED",
                details={"reason": error_msg, "prompt_snippet": prompt_text[:100]}
            )
            # Raise terminal exception to immediately fail the turn instead of returning LlmResponse with error_message
            raise SecurityBlockException(f"Security Policy Violation: {error_msg}")

        # 2. Check for DRY RUN configuration (mock responses to save API call costs during tests)
        dry_run = callback_context.state.get("dry_run", False)
        if dry_run:
            agent_name = callback_context.agent_name
            sea_cost = callback_context.state.get("sea_cost", 450000)
            
            # Read CSV path from state or calculate thresholds dynamically
            csv_path = callback_context.state.get("kpis_csv_path", "data/quarterly_kpis.csv")
            try:
                import pandas as pd
                df_active = pd.read_csv(csv_path)
                ttm_rev = df_active["Revenue"].sum()
                ttm_exp = df_active["Expenses"].sum()
                danger_raw = ttm_rev * 0.75 - ttm_exp
                danger_thresh = round(danger_raw / 50000) * 50000
                risk_thresh = round((danger_thresh * 0.8) / 50000) * 50000
                roi_thresh = round((danger_thresh * 0.55) / 50000) * 50000
            except Exception:
                danger_thresh = 600000
                risk_thresh = 500000
                roi_thresh = 350000

            fin_stance = "Approve" if sea_cost <= roi_thresh else ("Reject" if sea_cost > danger_thresh else "Modify")
            risk_stance = "Modify" if sea_cost > risk_thresh else "Approve"
            
            mock_text = ""
            if agent_name == "finance_agent":
                mock_text = f"""STANCE: {fin_stance}
CONFIDENCE: 0.92
KEY EVIDENCE:
- [Dry Run] Operating expenses verified at quarterly average benchmarks.
- [Dry Run] Simulated Cost parameter is ${sea_cost:,}.
- [Dry Run] ROI matches threshold margins.
ASSUMPTIONS:
- [Dry Run] Standard corporate tax rates apply.
ANALYSIS:
This is a dry-run mock response. Operating margins remain stable under simulated parameters.
"""
            elif agent_name == "marketing_agent":
                mock_text = f"""STANCE: Approve
CONFIDENCE: 0.88
KEY EVIDENCE:
- [Dry Run] LTV is calculated at $1,500, CAC is $320.
- [Dry Run] LTV:CAC ratio is extremely healthy at 4.69x.
ASSUMPTIONS:
- [Dry Run] Aggressive marketing captures early market dominance.
ANALYSIS:
This is a dry-run mock response. Marketing growth projections indicate high LTV:CAC efficiency justifies the expansion.
"""
            elif agent_name == "risk_agent":
                mock_text = f"""STANCE: {risk_stance}
CONFIDENCE: 0.90
KEY EVIDENCE:
- [Dry Run] Quantitative risk score is checked at 0.28.
- [Dry Run] Qualitative delay risk of 3-6 months is present.
ASSUMPTIONS:
- [Dry Run] Expansion capital exposure is bounded.
ANALYSIS:
This is a dry-run mock response. Suggests a phased entry strategy to mitigate licensing delay risks.
"""
            elif agent_name == "coordinator_synthesis":
                final_rec = "Approve Strategy"
                if fin_stance == "Reject":
                    final_rec = "Reject Strategy"
                elif fin_stance == "Modify" or risk_stance == "Modify":
                    final_rec = "Modify Parameters (Phased Launch)"
                    
                mock_text = f"""# Executive Decision Report

## 1. Final Recommendation
**{final_rec}** (Dry Run Tally)
- Finance Agent: {fin_stance} (Confidence: 0.92)
- Marketing Agent: Approve (Confidence: 0.88)
- Risk Agent: {risk_stance} (Confidence: 0.90)

## 2. Key Supporting Evidence
- [Dry Run] Operating margins meet targets if cost parameters are capped.
- [Dry Run] LTV:CAC ratio is highly efficient.

## 3. Consensus and Dissenting Views
- [Dry Run] Consensus achieved on market potential, but Finance and Risk advise parameter adjustments.

## 4. Core Assumptions & Simulated Parameters
- Southeast Asia entry cost: ${sea_cost:,}

## 5. Risk Assessment & Mitigations
- Recommends a phased launch to limit initial capital downside exposure.
"""
            else:
                mock_text = "[Dry Run] Default response."

            log_event(
                event_type="MODEL_DRY_RUN",
                actor=agent_name or "system",
                action="mock_response",
                status="SUCCESS",
                details={"model": "gemini-flash-latest-dryrun", "agent": agent_name}
            )
            
            block_part = types.Part.from_text(text=mock_text)
            block_content = types.Content(role="model", parts=[block_part])
            return LlmResponse(content=block_content)

        log_event(
            event_type="MODEL_CALL",
            actor=callback_context.agent_name or "system",
            action="request_sent",
            status="SUCCESS",
            details={"model": llm_request.model, "prompt_length": len(prompt_text)}
        )
        return None

    async def after_model_callback(self, **kwargs) -> LlmResponse | None:
        callback_context = kwargs.get("callback_context")
        llm_response = kwargs.get("llm_response")
        if not callback_context or not llm_response:
            return None

        response_text = ""
        if llm_response.content and llm_response.content.parts:
            response_text = llm_response.content.parts[0].text or ""

        log_event(
            event_type="MODEL_CALL",
            actor=callback_context.agent_name or "system",
            action="response_received",
            status="SUCCESS",
            details={"model": callback_context.node_path, "response_snippet": response_text[:100]}
        )
        return None

    async def before_tool_callback(self, **kwargs) -> dict | None:
        tool = kwargs.get("tool")
        args = kwargs.get("args") or kwargs.get("tool_args") or {}
        tool_context = kwargs.get("tool_context") or kwargs.get("context")
        
        if not tool or not tool_context:
            return None

        agent_name = tool_context.state.get("active_agent", "unknown")
        
        # Check permissions
        is_allowed = check_permission(agent_name, tool.name)
        if not is_allowed:
            block_reason = f"Security Violation: Agent '{agent_name}' is unauthorized to call tool '{tool.name}'."
            log_event(
                event_type="SECURITY_BLOCK",
                actor=agent_name,
                action="tool_execution",
                status="BLOCKED",
                details={"tool": tool.name, "args": args, "reason": block_reason}
            )
            return {
                "status": "error",
                "message": block_reason
            }

        # Handle tool output caching
        tool_cache = tool_context.state.setdefault("tool_cache", {})
        cache_key = f"{tool.name}:{json.dumps(args, sort_keys=True)}"
        if cache_key in tool_cache:
            cached_val = tool_cache[cache_key]
            discarded_keys = tool_context.state.setdefault("discarded_cache_keys", [])
            
            # If the cached response is valid OR we've already discarded/retried this key once, use it
            if is_valid_tool_response(cached_val) or cache_key in discarded_keys:
                log_event(
                    event_type="TOOL_CACHE_HIT",
                    actor=agent_name,
                    action="cache_retrieve",
                    status="SUCCESS",
                    details={"tool": tool.name, "args": args}
                )
                return cached_val
            else:
                # Discard bad cache entry and re-fetch once
                log_event(
                    event_type="TOOL_CACHE_DISCARD",
                    actor=agent_name,
                    action="cache_discard",
                    status="WARNING",
                    details={"tool": tool.name, "args": args, "bad_response": str(cached_val)[:200]}
                )
                discarded_keys.append(cache_key)
                tool_cache.pop(cache_key, None)

        log_event(
            event_type="TOOL_CALL",
            actor=agent_name,
            action="execution_started",
            status="SUCCESS",
            details={"tool": tool.name, "arguments": args}
        )
        return None

    async def after_tool_callback(self, **kwargs) -> dict | None:
        tool = kwargs.get("tool")
        tool_context = kwargs.get("tool_context") or kwargs.get("context")
        tool_response = kwargs.get("result") or kwargs.get("tool_response") or kwargs.get("response") or {}
        
        if not tool or not tool_context:
            return None

        agent_name = tool_context.state.get("active_agent", "unknown")
        log_event(
            event_type="TOOL_CALL",
            actor=agent_name,
            action="execution_completed",
            status="SUCCESS",
            details={"tool": tool.name, "response_snippet": str(tool_response)[:200]}
        )
        
        # Save output in cache
        tool_cache = tool_context.state.setdefault("tool_cache", {})
        args = kwargs.get("args") or kwargs.get("tool_args") or {}
        cache_key = f"{tool.name}:{json.dumps(args, sort_keys=True)}"
        tool_cache[cache_key] = tool_response
        return None


# ==============================================================================
# COORDINATOR AGENT: DEBATE ORCHESTRATION & SYNTHESIS
# Orchestrates a real 2-round multi-agent deliberation:
#   Round 1: Sequentially runs specialists, invoking real MCP tools with injected paths.
#   Round 2: Invokes synthesizer to compile the report.
# ==============================================================================
class CoordinatorAgent(BaseAgent):
    """Programmatic coordinator that runs a 2-round multi-agent deliberation loop:
    Round 1: Independent specialist analysis running live tool calling.
    Round 2: Report synthesis compilation by coordinator_synthesis.
    """
    finance_agent: Agent
    marketing_agent: Agent
    risk_agent: Agent
    model: RetryingGemini
    
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        # Parse decision question query
        user_query = ""
        for event in reversed(ctx.session.events):
            if event.author == "user":
                if event.content and hasattr(event.content, "parts") and event.content.parts:
                    user_query = "".join([p.text for p in event.content.parts if p.text])
                elif isinstance(event.content, str):
                    user_query = event.content
                break
        if not user_query:
            user_query = "Should NimbusFlow expand into Southeast Asia?"

        # Retrieve simulated variables & session database/PDF file paths
        sea_cost = ctx.session.state.get("sea_cost", 450000)
        region = ctx.session.state.get("active_region", "Southeast Asia")
        finance_db_path = ctx.session.state.get("finance_db_path", "data/business_data.db")
        marketing_pdf_path = ctx.session.state.get("marketing_pdf_path", "data/quarterly_business_report.pdf")
        cost_origin_message = ctx.session.state.get("cost_origin_message", "")
        
        # Read active CSV file to compute dynamic benchmarks
        csv_path = ctx.session.state.get("kpis_csv_path", "data/quarterly_kpis.csv")
        try:
            import pandas as pd
            df_active = pd.read_csv(csv_path)
            ltm_revenue = df_active["Revenue"].sum()
            ltm_expenses = df_active["Expenses"].sum()
            last_row = df_active.iloc[-1]
            quarterly_operating_profit = last_row["Revenue"] - last_row["Expenses"]
            
            approve_ceiling, phased_ceiling, reject_floor = get_cost_tiers(
                ltm_revenue, ltm_expenses, quarterly_operating_profit
            )
        except Exception:
            approve_ceiling = 507000.0
            phased_ceiling = 700000.0
            reject_floor = 855000.0

        # Calculate deterministic expected stances based on cost tiers
        expected_finance_stance = "Approve" if sea_cost <= approve_ceiling else ("Reject" if sea_cost > reject_floor else "Modify")
        expected_risk_stance = "Modify" if sea_cost > phased_ceiling else "Approve"

        log_event(
            event_type="USER_QUERY",
            actor="user",
            action="submitted_query",
            status="SUCCESS",
            details={
                "query": user_query,
                "sea_cost": sea_cost,
                "finance_db_path": finance_db_path,
                "marketing_pdf_path": marketing_pdf_path
            }
        )

        yield make_event(self.name, f"Starting 2-Round deliberation for {region} expansion (Cost Parameter: ${sea_cost:,})...")
        await asyncio.sleep(0.5)

        # Save original events history
        original_events = list(ctx.session.events)

        # ==========================================
        # ROUND 1: Independent Specialist Analysis
        # ==========================================
        
        # -- 1. Finance Agent Run --
        yield make_event(self.name, "[Round 1] Finance Agent analyzing KPIs and cost-sensitivity...")
        finance_prompt = (
            f"User Query: {user_query}\n"
            f"Projected {region} Entry Cost Parameter: ${sea_cost:,} ({cost_origin_message})\n\n"
            f"CRITICAL FILE INSTRUCTION:\n"
            f"You MUST query the specific SQLite database at path: '{finance_db_path}'.\n"
            f"When invoking the tool 'run_query', you must pass the argument db_path='{finance_db_path}' explicitly.\n\n"
            f"DETERMINISTIC COST RULE ASSIGNMENT (You MUST cite these exact figures; do NOT invent alternative thresholds):\n"
            f"- Approve zone: cost is <= ${approve_ceiling:,.0f} (Representing a low, board-acceptable share of trailing annual profit, ~15% of annual profit)\n"
            f"- Reject zone: cost is > ${reject_floor:,.0f} (Point at which this cost would breach the 25% margin floor on trailing revenue)\n"
            f"Based on the projected cost of ${sea_cost:,}:\n"
            f"- Since cost is <= ${approve_ceiling:,.0f}, the cost is in the Approve zone.\n"
            f"- Since cost is > ${reject_floor:,.0f}, the cost is in the Reject zone.\n"
            f"- Otherwise, the cost is in the Modify zone.\n"
            f"YOUR DETERMINED STANCE MUST BE: {expected_finance_stance}.\n"
            f"Please perform your independent Round 1 analysis, cite the exact figures above, and output STANCE: {expected_finance_stance}."
        )
        ctx.session.events = [make_event("user", finance_prompt)]
        finance_r1 = ""
        async for event in self.finance_agent.run_async(ctx):
            if event.content and event.content.parts:
                finance_r1 = "".join([part.text for part in event.content.parts if part.text])
            yield event

        # Proactive delay to avoid Gemini free-tier RPM limits
        await asyncio.sleep(2.5)

        # -- 2. Marketing Agent Run --
        yield make_event(self.name, "[Round 1] Marketing Agent analyzing spend efficiency and LTV/CAC...")
        marketing_prompt = (
            f"User Query: {user_query}\n"
            f"Projected {region} Entry Cost Parameter: ${sea_cost:,} ({cost_origin_message})\n\n"
            f"CRITICAL FILE INSTRUCTION:\n"
            f"You MUST read qualitative details from the PDF file at path: '{marketing_pdf_path}'.\n"
            f"When invoking the tool 'read_pdf', you must pass the argument filepath='{marketing_pdf_path}' explicitly.\n\n"
            f"Please perform your independent Round 1 analysis."
        )
        ctx.session.events = [make_event("user", marketing_prompt)]
        marketing_r1 = ""
        async for event in self.marketing_agent.run_async(ctx):
            if event.content and event.content.parts:
                marketing_r1 = "".join([part.text for part in event.content.parts if part.text])
            yield event

        # Proactive delay to avoid Gemini free-tier RPM limits
        await asyncio.sleep(2.5)

        # -- 3. Risk Agent Run --
        yield make_event(self.name, "[Round 1] Risk Agent reviewing report PDF and compliance metrics...")
        risk_prompt = (
            f"User Query: {user_query}\n"
            f"Projected {region} Entry Cost Parameter: ${sea_cost:,} ({cost_origin_message})\n\n"
            f"CRITICAL FILE INSTRUCTIONS:\n"
            f"- You MUST query the SQLite database at path: '{finance_db_path}' (passing db_path='{finance_db_path}' to 'run_query').\n"
            f"- You MUST read the PDF report at path: '{marketing_pdf_path}' (passing filepath='{marketing_pdf_path}' to 'read_pdf').\n\n"
            f"DETERMINISTIC COST RULE ASSIGNMENT (You MUST cite these exact figures; do NOT invent alternative thresholds):\n"
            f"- Phased launch ceiling: ${phased_ceiling:,.0f} (Point above which the cost exceeds one quarter's operating profit, requiring a phased launch to limit initial capital downside exposure)\n"
            f"Based on the projected cost of ${sea_cost:,}:\n"
            f"- Since cost is > ${phased_ceiling:,.0f}, you advocate for a phased launch.\n"
            f"- Otherwise, your stance is Approve.\n"
            f"YOUR DETERMINED STANCE MUST BE: {expected_risk_stance}.\n"
            f"Please perform your independent Round 1 analysis, cite the exact figures above, and output STANCE: {expected_risk_stance}."
        )
        ctx.session.events = [make_event("user", risk_prompt)]
        risk_r1 = ""
        async for event in self.risk_agent.run_async(ctx):
            if event.content and event.content.parts:
                risk_r1 = "".join([part.text for part in event.content.parts if part.text])
            yield event

        # Save Round 1 results in state
        ctx.session.state["finance_round1"] = finance_r1
        ctx.session.state["marketing_round1"] = marketing_r1
        ctx.session.state["risk_round1"] = risk_r1

        log_event(
            event_type="DEBATE_ROUND",
            actor=self.name,
            action="round_1_completed",
            status="SUCCESS",
            details={"finance_r1": finance_r1, "marketing_r1": marketing_r1, "risk_r1": risk_r1}
        )

        # Proactive delay to avoid Gemini free-tier RPM limits
        await asyncio.sleep(2.5)

        # ==========================================
        # ROUND 2: Report Synthesis Compilation
        # ==========================================
        yield make_event(self.name, "[Round 2] Coordinating and synthesizing final Executive Decision Report...")
        
        synthesis_prompt = f"""Here is the user query: {user_query}
Projected {region} Entry Cost Parameter: ${sea_cost:,}

Here are the independent Round 1 analyses from the specialists:

=== FINANCE AGENT ROUND 1 ===
{finance_r1}

=== MARKETING AGENT ROUND 1 ===
{marketing_r1}

=== RISK AGENT ROUND 1 ===
{risk_r1}

Please write the final Executive Decision Report.
Follow these requirements:
1. Stance Tally: Summarize the final stances (Approve / Modify / Reject) and calculate a confidence-weighted tally.
2. Areas of consensus and remaining disagreements.
3. Final Recommended decision path.
4. Format EXACTLY using the markdown layout below:

# Executive Decision Report

## 1. Final Recommendation
[Detail recommendation and weighted score tally]

## 2. Key Supporting Evidence
[Bullet points of financial, marketing, and compliance evidence]

## 3. Consensus and Dissenting Views
[Describe agreed points and remaining disagreements]

## 4. Core Assumptions & Simulated Parameters
- {region} entry cost: ${sea_cost:,}
- [Other key assumptions]

## 5. Risk Assessment & Mitigations
- [List critical risks and suggested phased launch/mitigations]
"""
        ctx.session.events = [make_event("user", synthesis_prompt)]
        
        final_report = ""
        async for event in coordinator_synthesis_agent.run_async(ctx):
            if event.content and event.content.parts:
                final_report = "".join([part.text for part in event.content.parts if part.text])
            yield event

        # Save report in state for direct retrieval
        ctx.session.state["final_report"] = final_report

        log_event(
            event_type="DEBATE_ROUND",
            actor=self.name,
            action="round_2_completed",
            status="SUCCESS",
            details={"report": final_report}
        )

        # Restore original events and append final synthesized report
        final_event = make_event(self.name, final_report)
        ctx.session.events = original_events + [final_event]

        # Yield the final state delta to commit to the runner's session service state
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part.from_text(text="")]),
            actions=EventActions(
                state_delta={
                    "finance_round1": finance_r1,
                    "marketing_round1": marketing_r1,
                    "risk_round1": risk_r1,
                    "final_report": final_report
                }
            )
        )

# Instantiate the Coordinator Agent
# Declares class fields for pydantic validation mapping
coordinator_agent = CoordinatorAgent(
    name="coordinator",
    finance_agent=finance_agent,
    marketing_agent=marketing_agent,
    risk_agent=risk_agent,
    model=RetryingGemini(model="gemini-flash-latest"),
    description="Orchestrates 2-round deliberation between Finance, Marketing, and Risk agents and generates executive report."
)
