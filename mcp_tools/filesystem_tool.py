import os
from mcp.server.fastmcp import FastMCP

# Define the FastMCP server
mcp = FastMCP("Filesystem Tool")

# Reference the root of the project workspace
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def check_safe_path(relative_path: str) -> tuple[bool, str]:
    """Helper to check if path is safe (stays within workspace)."""
    abs_path = os.path.abspath(os.path.join(WORKSPACE_DIR, relative_path))
    if not abs_path.startswith(WORKSPACE_DIR):
        return False, "Error: Access denied. Path traversal outside workspace is blocked."
    return True, abs_path

@mcp.tool()
def list_files(directory: str = "data") -> str:
    """Lists files in a specific directory within the workspace.
    
    Args:
        directory: The relative path of the directory to list (e.g. 'data').
        
    Returns:
        A list of filenames in the directory, or an error message.
    """
    is_safe, abs_path = check_safe_path(directory)
    if not is_safe:
        return abs_path
        
    try:
        if not os.path.exists(abs_path):
            return f"Error: Directory '{directory}' does not exist."
        if not os.path.isdir(abs_path):
            return f"Error: '{directory}' is not a directory."
            
        files = os.listdir(abs_path)
        return str(files)
    except Exception as e:
        return f"Error listing files in '{directory}': {str(e)}"

@mcp.tool()
def read_file(filepath: str) -> str:
    """Reads the contents of a local text file within the workspace.
    
    Args:
        filepath: The relative path of the file to read (e.g. 'data/quarterly_kpis.csv').
        
    Returns:
        The content of the file as a string, or an error message.
    """
    is_safe, abs_path = check_safe_path(filepath)
    if not is_safe:
        return abs_path
        
    try:
        if not os.path.exists(abs_path):
            return f"Error: File '{filepath}' does not exist."
        if os.path.isdir(abs_path):
            return f"Error: '{filepath}' is a directory, not a file."
            
        # Avoid reading huge files to protect context window size
        file_size = os.path.getsize(abs_path)
        if file_size > 100 * 1024:  # 100KB limit
            return f"Error: File '{filepath}' is too large ({file_size} bytes). Max readable size is 100KB."
            
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"Error reading file '{filepath}': {str(e)}"

if __name__ == "__main__":
    mcp.run()
