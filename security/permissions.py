def check_permission(agent_name: str, tool_name: str) -> bool:
    """Enforces role-based permissions on tool usage for agents.
    
    Args:
        agent_name: Name of the agent attempting to call the tool.
        tool_name: Name of the tool being executed (e.g. 'calculate' or 'sqlite_tool__run_query').
        
    Returns:
        True if the agent is authorized to call the tool, False otherwise.
    """
    if not agent_name:
        return False
        
    agent_clean = agent_name.strip().lower()
    tool_clean = tool_name.strip().lower()
    
    # Allowed tools per agent
    # We use base tool names which will be matched as substrings to handle MCP naming prefixes
    allowed_mappings = {
        "finance_agent": ["calculate", "run_query", "list_files", "read_file"],
        "marketing_agent": ["calculate", "run_query", "list_files", "read_file", "read_pdf"],
        "risk_agent": ["calculate", "run_query", "list_files", "read_file", "read_pdf"],
        # coordinator_synthesis is the coordinator's synthesis step agent
        "coordinator_synthesis": [],
        # Coordinator is restricted from calling direct database, file, or PDF tools
        # to ensure it remains a pure reasoning/routing agent.
        "coordinator": [],
    }
    
    # Allow any test agents or default agents if they run outside the main debate flow
    # but strictly enforce for our debate agents
    if agent_clean not in allowed_mappings:
        # Default behavior: block unless explicitly authorized
        return False
        
    allowed_list = allowed_mappings[agent_clean]
    
    # Check if any allowed tool matches as a substring of the requested tool_name
    for allowed_tool in allowed_list:
        if allowed_tool in tool_clean:
            return True
            
    return False
