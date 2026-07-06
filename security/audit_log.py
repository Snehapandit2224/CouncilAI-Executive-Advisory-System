import os
import json
import datetime
import sys

AUDIT_LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "audit.log"))

def safe_serialize(obj):
    """Recursively serializes complex objects (like Pydantic models or GenAI types) into JSON-serializable types."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return safe_serialize(obj.model_dump())
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return safe_serialize(obj.dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {k: safe_serialize(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
        except Exception:
            pass
    if isinstance(obj, list):
        return [safe_serialize(x) for x in obj]
    if isinstance(obj, tuple):
        return [safe_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    return str(obj)

def log_event(event_type: str, actor: str, action: str, status: str, details: dict = None) -> None:
    """Appends a structured audit log entry to data/audit.log.
    
    Args:
        event_type: Category of event (e.g. 'USER_QUERY', 'AGENT_RUN', 'TOOL_CALL', 'SECURITY_BLOCK', 'HUMAN_DECISION')
        actor: Who performed the action (e.g. 'user', 'coordinator', 'finance_agent')
        action: Short description of action (e.g. 'submitted_query', 'run_round_1', 'calculate_profit', 'blocked_tool')
        status: Outcome status ('SUCCESS', 'FAILED', 'BLOCKED', 'ERROR')
        details: Additional key-value information (e.g., query params, tool arguments, block reasons)
    """
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "actor": actor,
        "action": action,
        "status": status,
        "details": safe_serialize(details or {})
    }
    
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"Failed to write to audit log: {e}", file=sys.stderr)

def read_audit_log(limit: int = 100) -> list[dict]:
    """Reads the latest entries from the audit log.
    
    Args:
        limit: Maximum number of recent entries to return.
        
    Returns:
        List of log entries as dicts, ordered newest first.
    """
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
        
    entries = []
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line.strip()))
        # Return last N items reversed (newest first)
        return entries[-limit:][::-1]
    except Exception as e:
        print(f"Failed to read audit log: {e}")
        return []
