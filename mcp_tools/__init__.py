import os
import sys
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

def get_mcp_toolset(name: str) -> McpToolset:
    """Instantiates an McpToolset for a local Python-based Stdio MCP server.
    
    Args:
        name: The base name of the tool script (e.g. 'calculator', 'sqlite', 'filesystem', 'pdf').
        
    Returns:
        An initialized McpToolset.
    """
    script_name = f"{name}_tool.py"
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), script_name))
    
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"MCP server script not found: {script_path}")
        
    # Use sys.executable to ensure we run inside the same virtual environment (e.g., .venv)
    python_exe = sys.executable
    
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=python_exe,
                args=[script_path]
            )
        )
    )
