import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import asyncio
import os
import sys
import re
import uuid
import sqlite3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure streamlit page parameters
st.set_page_config(
    page_title="CouncilAI | Business Decision Intelligence",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium styling (HSL tailored dark/light theme accents)
st.markdown("""
<style>
    .reportview-container {
        background: #0B0F19;
    }
    .main {
        background: #0B0F19;
        color: #F3F4F6;
    }
    h1, h2, h3 {
        color: #10B981 !important;
        font-family: 'Inter', sans-serif;
    }
    .stTabs button, div[data-baseweb="tab-list"] button {
        font-size: 1.25rem !important;
        font-weight: 600 !important;
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    .glass-card {
        background: rgba(17, 24, 39, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 20px;
        backdrop-filter: blur(12px);
    }
    .debate-round-header {
        color: #60A5FA;
        font-weight: bold;
        border-left: 4px solid #3B82F6;
        padding-left: 10px;
        margin-top: 15px;
        margin-bottom: 10px;
    }
    .agent-card-finance {
        background: rgba(16, 185, 129, 0.12);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 10px;
        color: #E6FDF4;
    }
    .agent-card-marketing {
        background: rgba(59, 130, 246, 0.12);
        border: 1px solid rgba(59, 130, 246, 0.3);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 10px;
        color: #EEF2FF;
    }
    .agent-card-risk {
        background: rgba(245, 158, 11, 0.12);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 10px;
        color: #FFFBEB;
    }
    .agent-title {
        font-weight: bold;
        font-size: 1.15em;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .agent-title-finance { color: #10B981; }
    .agent-title-marketing { color: #3B82F6; }
    .agent-title-risk { color: #F59E0B; }
""", unsafe_allow_html=True)

# Ensure project root is in the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google.adk.runners import InMemoryRunner
from google.genai import types
from agents.coordinator import coordinator_agent, SecurityAuditPlugin
from security.audit_log import read_audit_log, log_event
from security.input_guard import validate_input, validate_relevance_to_pdf

def escape_latex_dollar(text: str) -> str:
    """Escapes literal $ characters by converting them to the HTML entity &#36; to prevent Streamlit from interpreting them as LaTeX."""
    if not text:
        return ""
    return text.replace("$", "&#36;")

def get_cost_tiers(ltm_revenue, ltm_expenses, quarterly_operating_profit, margin_floor=0.25):
    """Calculates deterministic cost-tier thresholds from trailing financial data."""
    ttm_operating_profit = ltm_revenue - ltm_expenses
    approve_ceiling = 0.15 * ttm_operating_profit          # ~15% of annual profit
    phased_ceiling = quarterly_operating_profit             # one quarter's profit
    reject_floor = (ltm_revenue * (1 - margin_floor)) - ltm_expenses  # margin-floor breach point
    return approve_ceiling, phased_ceiling, reject_floor

def extract_region_from_pdf(pdf_path: str) -> str:
    """Extracts region name from the qualitative PDF report."""
    if not os.path.exists(pdf_path):
        return "Southeast Asia"
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        text_lower = text.lower()
        if "latin america" in text_lower or "brazil" in text_lower or "mexico" in text_lower:
            return "Latin America"
        if "europe" in text_lower:
            return "Europe"
    except Exception:
        pass
    return "Southeast Asia"

def extract_entry_cost_from_pdf(pdf_path: str) -> int | None:
    """Finds dollar figures near entry cost keywords in the PDF."""
    if not os.path.exists(pdf_path):
        return None
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
            
        text_lower = text.lower()
        import re
        matches = re.finditer(r'\$\s*([0-9,.]+)\s*([kKmM]?)', text)
        
        candidates = []
        for m in matches:
            num_str = m.group(1).replace(",", "")
            suffix = m.group(2).lower()
            try:
                if "." in num_str:
                    val = float(num_str)
                else:
                    val = int(num_str)
                    
                if suffix == "k":
                    val = int(val * 1000)
                elif suffix == "m":
                    val = int(val * 1000000)
                else:
                    val = int(val)
                candidates.append((val, m.start()))
            except Exception:
                continue
                
        keywords = ["entry cost", "year 1", "investment", "baseline", "initial budget", "budget"]
        best_candidate = None
        min_dist = float("inf")
        
        for kw in keywords:
            kw_indices = [m.start() for m in re.finditer(re.escape(kw), text_lower)]
            for kw_idx in kw_indices:
                for val, pos in candidates:
                    dist = abs(pos - kw_idx)
                    if dist < 150:
                        if dist < min_dist:
                            min_dist = dist
                            best_candidate = val
                            
        if best_candidate and best_candidate >= 10000:
            return best_candidate
            
        for val, pos in candidates:
            if val >= 50000:
                return val
    except Exception:
        pass
    return None

# 1. Initialize Unique Session ID for Isolation
if "session_uuid" not in st.session_state:
    st.session_state["session_uuid"] = str(uuid.uuid4())[:8]
session_id = st.session_state["session_uuid"]

DEFAULT_CSV_PATH = "data/quarterly_kpis.csv"
DEFAULT_DB_PATH = "data/business_data.db"
DEFAULT_PDF_PATH = "data/quarterly_business_report.pdf"

# Initialize state-based file paths
if "finance_db_path" not in st.session_state:
    st.session_state["finance_db_path"] = DEFAULT_DB_PATH
if "marketing_pdf_path" not in st.session_state:
    st.session_state["marketing_pdf_path"] = DEFAULT_PDF_PATH
if "kpis_csv_path" not in st.session_state:
    st.session_state["kpis_csv_path"] = DEFAULT_CSV_PATH
if "active_region" not in st.session_state:
    st.session_state["active_region"] = extract_region_from_pdf(DEFAULT_PDF_PATH)
if "extracted_cost" not in st.session_state:
    st.session_state["extracted_cost"] = extract_entry_cost_from_pdf(DEFAULT_PDF_PATH)
if "cost_extracted_from_pdf" not in st.session_state:
    st.session_state["cost_extracted_from_pdf"] = (st.session_state.get("extracted_cost") is not None)

def load_kpis():
    csv_path = st.session_state["kpis_csv_path"]
    if os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path)
        except Exception:
            pass
    return pd.DataFrame()

# Main Title & Subheader
st.title("🤖 CouncilAI Deliberation Dashboard")
st.markdown("##### Explainable Multi-Agent Business Decision Intelligence System")
st.markdown("---")

# Load KPIs to derive dynamic sliders
df_kpis = load_kpis()

# Sidebar: Simulator and Dry Run configurations
with st.sidebar:
    st.markdown("### 🛠️ Scenario Simulator")
    st.write("Adjust entry cost assumptions to observe recommendation dynamics.")
    
    # 2. Derive cost slider range and benchmarks dynamically
    if not df_kpis.empty and "Revenue" in df_kpis.columns:
        try:
            max_rev = int(df_kpis["Revenue"].max())
            extracted_val = st.session_state.get("extracted_cost")
            cost_extracted = st.session_state.get("cost_extracted_from_pdf", False)
            
            # Compute dynamic benchmarks using trailing data cost tiers formula
            ltm_revenue = int(df_kpis["Revenue"].sum())
            ltm_expenses = int(df_kpis["Expenses"].sum())
            last_row = df_kpis.iloc[-1]
            quarterly_operating_profit = int(last_row["Revenue"] - last_row["Expenses"])
            
            approve_ceiling, phased_ceiling, reject_floor = get_cost_tiers(
                ltm_revenue, ltm_expenses, quarterly_operating_profit
            )
            
            # Lower bound is 50,000 or lower to prevent clamping the PDF stated cost
            min_slider = 50000
            # Ensure the slider dynamically extends to cover all computed threshold boundaries (up to 1.3x reject_floor)
            max_slider = max(int(max_rev * 1.2), (extracted_val * 2) if extracted_val else 1000000, int(reject_floor * 1.3))
            
            # Round slider bounds to nearest 10,000 for clean aesthetics
            min_slider = (min_slider // 10000) * 10000
            max_slider = ((max_slider + 9999) // 10000) * 10000
            
            # Use extracted cost from PDF if available, clamp to bounds
            if cost_extracted and extracted_val is not None:
                default_slider = min(max_slider, max(min_slider, extracted_val))
                slider_label = f"Baseline entry cost (from uploaded report): ${extracted_val:,} — adjust to simulate alternative scenarios."
            else:
                default_val = int(max_rev * 0.4)
                default_slider = min(max_slider, max(min_slider, default_val))
                slider_label = f"Estimated default entry cost (not in report): ${default_slider:,} — adjust to simulate alternative scenarios."
        except Exception:
            min_slider, max_slider, default_slider = 50000, 1000000, 450000
            slider_label = "Entry Cost Parameter"
            approve_ceiling, phased_ceiling, reject_floor = 507000.0, 700000.0, 855000.0
    else:
        min_slider, max_slider, default_slider = 50000, 1000000, 450000
        slider_label = "Entry Cost Parameter"
        approve_ceiling, phased_ceiling, reject_floor = 507000.0, 700000.0, 855000.0
        
    region = st.session_state.get("active_region", "Southeast Asia")
    
    # Initialize cost_param in session state
    if "cost_param" not in st.session_state:
        st.session_state["cost_param"] = int(default_slider)
        
    # Reset cost_param if default_slider changes (e.g. due to uploading a new dataset)
    if st.session_state.get("last_default_slider") != default_slider:
        st.session_state["cost_param"] = int(default_slider)
        st.session_state["last_default_slider"] = default_slider
        
    # Ensure current cost_param is clamped within the active slider bounds to prevent Streamlit layout exceptions
    st.session_state["cost_param"] = min(max_slider, max(min_slider, st.session_state["cost_param"]))
        
    # Slider for entry cost adjustments
    slider_cost = st.slider(
        slider_label,
        min_value=min_slider,
        max_value=max_slider,
        value=st.session_state["cost_param"],
        step=5000,
        format="$%d",
        disabled=st.session_state.get("is_running", False),
        key="cost_slider_widget"
    )
    st.session_state["cost_param"] = slider_cost
        
    # Determine cost origin message
    slider_value = st.session_state["cost_param"]
    sea_cost = slider_value
    extracted_val = st.session_state.get("extracted_cost")
    cost_extracted = st.session_state.get("cost_extracted_from_pdf", False)
    
    if cost_extracted and extracted_val is not None:
        if slider_value == extracted_val:
            cost_origin_message = "This is the cost stated in the uploaded report."
        else:
            cost_origin_message = f"This is a simulated what-if value the user has set, different from the report's stated ${extracted_val:,}."
    else:
        if slider_value == default_slider:
            cost_origin_message = "This is an estimated default cost (not stated in the report)."
        else:
            cost_origin_message = f"This is a simulated what-if value the user has set, different from the estimated default of ${default_slider:,}."
            
    st.info(
        f"**Cost Rule Benchmarks:**\n"
        f"- **Approve ceiling (${approve_ceiling/1000:,.1f}k)**: Low, board-acceptable share of trailing annual profit (~15% of annual profit)\n"
        f"- **Phased launch ceiling (${phased_ceiling/1000:,.1f}k)**: Cost exceeds one quarter's operating profit, requiring a phased launch\n"
        f"- **Reject floor (${reject_floor/1000:,.1f}k)**: Cost would breach the 25% margin floor on trailing revenue"
    )
    
    st.markdown("---")
    st.markdown("### ⚙️ Demo Configurations")
    # Dry Run toggle
    dry_run = st.checkbox(
        "Enable Dry Run Mode",
        value=False,
        help="Runs the debate loop instantly using pre-cached/mocked model responses to save Gemini quota.",
        disabled=st.session_state.get("is_running", False)
    )
    st.caption("⚡ Bypasses the Gemini API and returns instant cost-sensitive mock responses.")
    
    # Active file assets indicator in sidebar
    st.markdown("---")
    st.markdown("### 📁 Active Data Assets")
    st.caption(f"📊 **KPIs CSV:** `{os.path.basename(st.session_state.get('kpis_csv_path', DEFAULT_CSV_PATH))}`")
    st.caption(f"📄 **Business PDF:** `{os.path.basename(st.session_state.get('marketing_pdf_path', DEFAULT_PDF_PATH))}`")
    
    st.markdown("---")
    st.markdown("### 📋 Executive Query Context")
    query_text = st.text_area(
        "Decision Question",
        value="Should NimbusFlow expand into Southeast Asia?",
        height=100,
        disabled=st.session_state.get("is_running", False)
    )

    # Dynamic status sentence indicator below decision question
    st.markdown("---")
    st.markdown("### 🏛️ Corporate Resolution Status")
    if st.session_state.get("resolution_submitted", False):
        action = st.session_state.get("human_resolution_action", "N/A")
        cost = st.session_state.get("debate_cost", 450000)
        st.success(f"**Resolution**: {action} (Cost: ${cost:,})")
    elif "debate_state" in st.session_state:
        state = st.session_state["debate_state"]
        final_stance = "Approve"
        report_text_lower = state.get("final_report", "").lower()
        if "reject strategy" in report_text_lower:
            final_stance = "Reject"
        elif "modify parameters" in report_text_lower or "phased launch" in report_text_lower or "modify stance" in report_text_lower or "modify" in report_text_lower:
            final_stance = "Modify"
        st.warning(f"**Deliberation Tally**: {final_stance}\n\n⚠️ **Status**: Pending Human Approval")
    else:
        st.write("Deliberation Status: *Pending Run*")

# Visual KPI Dashboard (Plotly Charts)
st.markdown("### 📊 Business Performance Dashboard")
if not df_kpis.empty:
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Chart 1: Revenue vs Expenses
        fig_rev = go.Figure()
        fig_rev.add_trace(go.Bar(
            x=df_kpis["Quarter"], y=df_kpis["Revenue"],
            name="Revenue", marker_color="#10B981"
        ))
        fig_rev.add_trace(go.Bar(
            x=df_kpis["Quarter"], y=df_kpis["Expenses"],
            name="Expenses", marker_color="#E11D48"
        ))
        fig_rev.update_layout(
            template="plotly_dark",
            title="Quarterly Revenue vs Expenses",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#F3F4F6",
            barmode="group",
            margin=dict(l=20, r=20, t=40, b=20),
            height=250
        )
        st.plotly_chart(fig_rev, use_container_width=True)
        
    with col2:
        # Chart 2: Marketing CAC vs LTV
        fig_mkt = go.Figure()
        fig_mkt.add_trace(go.Scatter(
            x=df_kpis["Quarter"], y=df_kpis["LTV"],
            name="LTV", line=dict(color="#3B82F6", width=3)
        ))
        fig_mkt.add_trace(go.Scatter(
            x=df_kpis["Quarter"], y=df_kpis["CAC"],
            name="CAC", line=dict(color="#FB7185", width=3, dash='dash')
        ))
        fig_mkt.update_layout(
            template="plotly_dark",
            title="LTV vs CAC Trend",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#F3F4F6",
            margin=dict(l=20, r=20, t=40, b=20),
            height=250
        )
        st.plotly_chart(fig_mkt, use_container_width=True)
        
    with col3:
        # Chart 3: Risk Score
        fig_risk = px.line(
            df_kpis, x="Quarter", y="Risk_Score",
            title="Internal Risk Score Trend",
            color_discrete_sequence=["#F59E0B"]
        )
        fig_risk.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#F3F4F6",
            margin=dict(l=20, r=20, t=40, b=20),
            height=250
        )
        st.plotly_chart(fig_risk, use_container_width=True)
else:
    st.warning("No KPI data found. Please upload KPI data in the 'Data & Audit Log' tab.")

# Restructure layout into three main tabs
tab_debate, tab_report, tab_data = st.tabs(["🗣️ Live Deliberation Debate", "📜 Executive Report & Tally", "📁 Data & Security Logs"])

def cleanup_orphaned_mcp_servers():
    import subprocess
    try:
        # Terminate any python processes running the MCP server scripts to avoid deadlocks on closed event loops
        subprocess.run('wmic process where "CommandLine like \'%_tool.py%\'" call terminate', shell=True, capture_output=True)
    except Exception:
        pass

async def execute_debate(query: str, cost: int, region: str, cost_origin_message: str, dry_run_active: bool, live_timeline, status_box, progress_bar):
    # Terminate any orphaned tool servers to prevent deadlocks
    cleanup_orphaned_mcp_servers()

    # Run Input Guard validation on the query at the front gate
    is_safe, error_msg = validate_input(query)
    if not is_safe:
        st.error(error_msg)
        return None

    # Run dynamic PDF alignment check
    pdf_path = st.session_state.get("marketing_pdf_path", DEFAULT_PDF_PATH)
    is_aligned, alignment_err = validate_relevance_to_pdf(query, pdf_path)
    if not is_aligned:
        st.error(alignment_err)
        return None

    runner = InMemoryRunner(agent=coordinator_agent, app_name="agents", plugins=[SecurityAuditPlugin()])
    runner.auto_create_session = True
    
    # Check Gemini API Key unless in Dry Run
    if not dry_run_active and not os.getenv("GEMINI_API_KEY"):
        st.error("Error: `GEMINI_API_KEY` is not set. Please add it to your `.env` file to execute live model calls.")
        return None
        
    steps = []
    
    try:
        user_message = types.Content(role="user", parts=[types.Part.from_text(text=query)])
        
        async for event in runner.run_async(
            user_id="user_admin",
            session_id="local_session",
            new_message=user_message,
            state_delta={
                "sea_cost": cost,
                "active_region": region,
                "cost_origin_message": cost_origin_message,
                "dry_run": dry_run_active,
                "finance_db_path": st.session_state["finance_db_path"],
                "marketing_pdf_path": st.session_state["marketing_pdf_path"],
                "kpis_csv_path": st.session_state.get("kpis_csv_path", DEFAULT_CSV_PATH)
            }
        ):
            if event.content:
                text = ""
                if hasattr(event.content, "parts") and event.content.parts:
                    text = "".join([part.text for part in event.content.parts if part.text])
                elif isinstance(event.content, str):
                    text = event.content
                else:
                    text = str(event.content)
                
                if text:
                    # Capture structural logs and filter out raw markdown
                    if text.startswith("[Round") or text.startswith("Starting") or text.startswith("Assembling"):
                        steps.append(text)
                        
                        # Live progress status box updates
                        status_box.markdown(f"**Current step:** `{text}`")
                        
                        # Draw timeline dynamically
                        with live_timeline:
                            st.markdown("#### 🔄 Live Deliberation Timeline")
                            for step in steps:
                                st.markdown(f"🔹 {step}")
                                
                    # Increment progress bar
                    progress_bar.progress(min(len(steps) * 20, 100))
                    
        progress_bar.empty()
        status_box.success("Multi-agent deliberation and report synthesis completed!")
        
        # Retrieve session state
        session = await runner.session_service.get_session(
            app_name=runner.app_name,
            user_id="user_admin",
            session_id="local_session"
        )
        print("DEBUG execute_debate returned state keys:", list(session.state.keys()) if session else "Session is None")
        return session.state if session else None
    except Exception as e:
        progress_bar.empty()
        status_box.error(f"Error during debate: {str(e)}")
        return None
    finally:
        # Close all active toolset sessions while the event loop is still active
        for agent in [coordinator_agent.finance_agent, coordinator_agent.marketing_agent, coordinator_agent.risk_agent]:
            if hasattr(agent, "tools") and agent.tools:
                for toolset in agent.tools:
                    if hasattr(toolset, "close"):
                        try:
                            await toolset.close()
                        except Exception:
                            pass
        cleanup_orphaned_mcp_servers()

with tab_debate:
    st.markdown("### 💬 Multi-Agent Deliberation Control")
    trigger_debate = st.button("🚀 Run 2-Round Deliberation", type="primary", disabled=st.session_state.get("is_running", False))
    
    # Timeline containers
    status_box = st.empty()
    progress_bar = st.progress(0)
    live_timeline = st.empty()
    
    if trigger_debate:
        # Check mandatory dual uploader requirement
        has_custom_csv = st.session_state["kpis_csv_path"] != DEFAULT_CSV_PATH
        has_custom_pdf = st.session_state["marketing_pdf_path"] != DEFAULT_PDF_PATH
        
        if has_custom_csv != has_custom_pdf:
            progress_bar.empty()
            status_box.error(
                "⚠️ Error: Single-file customization is not allowed. "
                "You must upload **both** a custom quarterly KPIs CSV and a custom business report PDF "
                "to execute a customized deliberation. Otherwise, please use the default assets."
            )
        else:
            # Run debate
            st.session_state["is_running"] = True
            st.session_state["resolution_submitted"] = False
            
            region = st.session_state.get("active_region", "Southeast Asia")
            with st.spinner("Executing 2-round deliberation loop (Round 1 Specialists, Round 2 Synthesizer)..."):
                try:
                    # Run debate with a hard 3-minute timeout limit to prevent forever hanging
                    state = asyncio.run(asyncio.wait_for(
                        execute_debate(query_text, sea_cost, region, cost_origin_message, dry_run, live_timeline, status_box, progress_bar),
                        timeout=180.0
                    ))
                except asyncio.TimeoutError:
                    st.session_state["is_running"] = False
                    cleanup_orphaned_mcp_servers()
                    st.error("⏳ Hard Timeout Exceeded: The multi-agent deliberation loop timed out after 3 minutes. Please check your network or try again.")
                    state = None
                except Exception as ex:
                    st.session_state["is_running"] = False
                    cleanup_orphaned_mcp_servers()
                    st.error(f"❌ Deliberation aborted with error: {str(ex)}")
                    state = None
                
            st.session_state["is_running"] = False
                
            if state:
                st.session_state["debate_state"] = state
                st.session_state["debate_cost"] = sea_cost
                st.rerun()

    # Render debate stances if available
    if "debate_state" in st.session_state:
        state = st.session_state["debate_state"]
        cost = st.session_state["debate_cost"]
        
        st.markdown(f"### Specialist Stance Trace (Cost assumption: ${cost:,})")
        
        st.markdown("<div class='debate-round-header'>ROUND 1: Independent Analysis (Assigned MCP Tools)</div>", unsafe_allow_html=True)
        col_f1, col_m1, col_r1 = st.columns(3)
        
        with col_f1:
            st.markdown(
                f"<div class='agent-card-finance' style='max-height: 400px; overflow-y: auto;'>"
                f"<div class='agent-title agent-title-finance'>💵 Finance Agent (Round 1)</div>\n\n"
                f"<div style='white-space: pre-wrap;'>{escape_latex_dollar(state.get('finance_round1', 'N/A'))}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        with col_m1:
            st.markdown(
                f"<div class='agent-card-marketing' style='max-height: 400px; overflow-y: auto;'>"
                f"<div class='agent-title agent-title-marketing'>📈 Marketing Agent (Round 1)</div>\n\n"
                f"<div style='white-space: pre-wrap;'>{escape_latex_dollar(state.get('marketing_round1', 'N/A'))}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        with col_r1:
            st.markdown(
                f"<div class='agent-card-risk' style='max-height: 400px; overflow-y: auto;'>"
                f"<div class='agent-title agent-title-risk'>⚠️ Risk Agent (Round 1)</div>\n\n"
                f"<div style='white-space: pre-wrap;'>{escape_latex_dollar(state.get('risk_round1', 'N/A'))}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

# Tab 2: Executive Report & Stance Tally
with tab_report:
    if "debate_state" in st.session_state:
        state = st.session_state["debate_state"]
        cost = st.session_state["debate_cost"]
        
        # Parse confidence values for chart
        def extract_confidence(text: str) -> float:
            if not text:
                return 0.0
            match = re.search(r"CONFIDENCE:\s*(\d+\.?\d*)", text, re.IGNORECASE)
            return float(match.group(1)) if match else 0.5
            
        def extract_stance(text: str) -> str:
            if not text:
                return "Unknown"
            match = re.search(r"STANCE:\s*(\w+)", text, re.IGNORECASE)
            return match.group(1).title() if match else "Unknown"

        finance_conf = extract_confidence(state.get("finance_round1"))
        marketing_conf = extract_confidence(state.get("marketing_round1"))
        risk_conf = extract_confidence(state.get("risk_round1"))
        
        f_stance = extract_stance(state.get("finance_round1"))
        m_stance = extract_stance(state.get("marketing_round1"))
        r_stance = extract_stance(state.get("risk_round1"))
        
        # Parse final report stance
        final_stance = "Approve"
        report_text_lower = state.get("final_report", "").lower()
        if "reject strategy" in report_text_lower:
            final_stance = "Reject"
        elif "modify parameters" in report_text_lower or "phased launch" in report_text_lower or "modify stance" in report_text_lower or "modify" in report_text_lower:
            final_stance = "Modify"

        st.markdown("<div class='debate-round-header'>ROUND 2: Executive Deliberation Report & Tally</div>", unsafe_allow_html=True)
        
        col_rep, col_cht = st.columns([2, 1])
        with col_rep:
            st.markdown("### 📜 Executive Decision Report")
            with st.container(height=600):
                st.markdown(escape_latex_dollar(state.get('final_report', 'N/A')))
            
        with col_cht:
            st.markdown("#### 🎯 Agent Confidence Levels")
            fig = go.Figure(go.Bar(
                x=["Finance Agent", "Marketing Agent", "Risk Agent"],
                y=[finance_conf * 100, marketing_conf * 100, risk_conf * 100],
                marker_color=["#10B981", "#3B82F6", "#F59E0B"],
                text=[f"{finance_conf*100:.0f}%", f"{marketing_conf*100:.0f}%", f"{risk_conf*100:.0f}%"],
                textposition='auto',
                hovertemplate="<b>%{x}</b><br>Confidence: %{y:.0f}%<extra></extra>"
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#F3F4F6",
                yaxis=dict(title="Confidence (%)", range=[0, 100], gridcolor="rgba(255,255,255,0.05)"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                height=300,
                margin=dict(l=20, r=20, t=20, b=20)
            )
            st.plotly_chart(fig, use_container_width=True)

        # Side-by-Side Divergence Checks
        st.markdown("### 🔍 Agent Stance Divergence Check")
        st.write("Displays alignment between individual Round 1 specialist stances and the final synthesized Round 2 Executive Stance:")
        
        col_f, col_m, col_r = st.columns(3)
        with col_f:
            st.markdown(f"**Finance Stance (Round 1):** `{f_stance}`")
            if f_stance != "Unknown" and f_stance != final_stance:
                st.error(f"⚠️ Divergence: Stance overrides Finance Agent's stance ({f_stance} vs {final_stance})")
            else:
                st.success("✅ Aligned with Final Recommendation")
        with col_m:
            st.markdown(f"**Marketing Stance (Round 1):** `{m_stance}`")
            if m_stance != "Unknown" and m_stance != final_stance:
                st.error(f"⚠️ Divergence: Stance overrides Marketing Agent's stance ({m_stance} vs {final_stance})")
            else:
                st.success("✅ Aligned with Final Recommendation")
        with col_r:
            st.markdown(f"**Risk Stance (Round 1):** `{r_stance}`")
            if r_stance != "Unknown" and r_stance != final_stance:
                st.error(f"⚠️ Divergence: Stance overrides Risk Agent's stance ({r_stance} vs {final_stance})")
            else:
                st.success("✅ Aligned with Final Recommendation")
                
        # Human Resolution Panel
        st.markdown("---")
        st.markdown("### 🗳️ Human Resolution Panel")
        st.write("Review the compiled deliberation report and log your final corporate resolution:")
        
        is_resolved = st.session_state.get("resolution_submitted", False)
        
        col_approve, col_modify, col_reject = st.columns(3)
        with col_approve:
            if st.button("✅ Approve Strategy", use_container_width=True, disabled=is_resolved):
                st.session_state["human_action"] = "Approve"
        with col_modify:
            if st.button("⚠️ Modify Parameters", use_container_width=True, disabled=is_resolved):
                st.session_state["human_action"] = "Modify"
        with col_reject:
            if st.button("❌ Reject Strategy", use_container_width=True, disabled=is_resolved):
                st.session_state["human_action"] = "Reject"
                
        if is_resolved:
            st.success(f"Resolution Submitted: **{st.session_state.get('human_resolution_action', 'N/A')}**")
            st.info(f"**Rationale**: {st.session_state.get('human_resolution_rationale', '')}")
        elif "human_action" in st.session_state:
            action = st.session_state["human_action"]
            st.warning(f"You selected: **{action}**. Please provide your final rationale:")
            rationale = st.text_area("Resolution Rationale / Executive Notes", height=80)
            
            if st.button("Submit Resolution"):
                log_event(
                    event_type="HUMAN_DECISION",
                    actor="user_executive",
                    action=f"resolution_{action.lower()}",
                    status="SUCCESS",
                    details={"rationale": rationale, "cost_parameter": cost}
                )
                st.session_state["resolution_submitted"] = True
                st.session_state["human_resolution_action"] = action
                st.session_state["human_resolution_rationale"] = rationale
                del st.session_state["human_action"]
                st.success("Resolution logged to the security audit trail successfully!")
                st.rerun()
    else:
        st.info("Please run the deliberation simulation in the 'Live Deliberation Debate' tab first.")

# Tab 3: Data Uploaders, Database Explorer & Audit Trail
with tab_data:
    st.markdown("### 📁 Data Source Customization & Upload")
    st.write("Upload custom CSV metrics or business reports to isolate database queries for this session:")
    
    col_up_csv, col_up_pdf = st.columns(2)
    
    with col_up_csv:
        st.markdown("### 📊 1. KPIs CSV")
        st.caption("⚠️ Uploading both custom CSV and PDF is mandatory to run a customized deliberation.")
        st.markdown("**Required columns:** `Quarter, Revenue, Expenses, Marketing_Spend, CAC, LTV, Risk_Score, Compliance_Status`")
        
        # Enable downloading sample template CSV
        try:
            with open("data/quarterly_kpis.csv", "rb") as f:
                template_data = f.read()
            st.download_button(
                label="📥 Download Sample CSV",
                data=template_data,
                file_name="sample_quarterly_kpis.csv",
                mime="text/csv"
            )
        except Exception as e:
            st.error(f"Error loading template file: {str(e)}")
            
        uploaded_csv = st.file_uploader("Upload custom quarterly_kpis.csv", type=["csv"], disabled=st.session_state.get("is_running", False))
        if uploaded_csv:
            expected_csv_path = f"data/uploaded_kpis_{session_id}.csv"
            # Rerun loop protection guard
            if st.session_state.get("kpis_csv_path") != expected_csv_path:
                try:
                    # Load CSV to validate schema
                    uploaded_df = pd.read_csv(uploaded_csv)
                    required_cols = ["Quarter", "Revenue", "Expenses", "Marketing_Spend", "CAC", "LTV", "Risk_Score", "Compliance_Status"]
                    has_cols = all(col in uploaded_df.columns for col in required_cols)
                    
                    if has_cols:
                        # Save CSV
                        uploaded_df.to_csv(expected_csv_path, index=False)
                        st.session_state["kpis_csv_path"] = expected_csv_path
                        
                        # Compile to SQLite
                        db_path = f"data/uploaded_data_{session_id}.db"
                        conn = sqlite3.connect(db_path)
                        uploaded_df.to_sql("kpis", conn, if_exists="replace", index=False)
                        conn.close()
                        
                        st.session_state["finance_db_path"] = db_path
                        st.success(f"Custom CSV uploaded & compiled to SQLite successfully (Session Isolation: {session_id})!")
                        st.rerun()
                    else:
                        st.error(f"Invalid Schema! CSV must contain columns: {required_cols}")
                except Exception as e:
                    st.error(f"Error loading CSV file: {str(e)}")
                
    with col_up_pdf:
        st.markdown("### 📄 2. Business PDF")
        st.caption("⚠️ Uploading both custom CSV and PDF is mandatory to run a customized deliberation.")
        uploaded_pdf = st.file_uploader("Upload custom quarterly_business_report.pdf", type=["pdf"], disabled=st.session_state.get("is_running", False))
        if uploaded_pdf:
            expected_pdf_path = f"data/uploaded_report_{session_id}.pdf"
            # Rerun loop protection guard
            if st.session_state.get("marketing_pdf_path") != expected_pdf_path:
                try:
                    # Save PDF
                    with open(expected_pdf_path, "wb") as f:
                        f.write(uploaded_pdf.getbuffer())
                    st.session_state["marketing_pdf_path"] = expected_pdf_path
                    
                    # Extract cost and region dynamically
                    region = extract_region_from_pdf(expected_pdf_path)
                    st.session_state["active_region"] = region
                    
                    cost = extract_entry_cost_from_pdf(expected_pdf_path)
                    if cost is not None:
                        st.session_state["extracted_cost"] = cost
                        st.session_state["cost_extracted_from_pdf"] = True
                    else:
                        st.session_state["cost_extracted_from_pdf"] = False
                        st.session_state.pop("extracted_cost", None)
                        
                    cost_str = f"${cost:,}" if cost is not None else "Not Found"
                    st.success(f"Custom PDF uploaded successfully (Session Isolation: {session_id}, Region: {region}, Cost: {cost_str})!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error loading PDF file: {str(e)}")

    st.markdown("---")
    st.markdown("### 📊 Active Dataset Explorer")
    if not df_kpis.empty:
        st.info(
            f"📂 **Active KPIs CSV file:** `{st.session_state['kpis_csv_path']}`\n\n"
            f"📄 **Active Business PDF Report:** `{st.session_state['marketing_pdf_path']}`"
        )
        st.write("Displaying active KPIs data table:")
        st.dataframe(df_kpis, use_container_width=True)
    else:
        st.warning("No KPI data found.")

    st.markdown("---")
    st.markdown("### 🛡️ Security Audit Log Trail")
    if st.button("🔄 Refresh Audit Trails"):
        st.rerun()
        
    logs = read_audit_log(limit=50)
    if logs:
        st.dataframe(pd.DataFrame(logs), use_container_width=True)
    else:
        st.info("No security events logged yet.")
