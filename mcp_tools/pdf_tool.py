import os
from mcp.server.fastmcp import FastMCP
from pypdf import PdfReader

# Define the FastMCP server
mcp = FastMCP("PDF Tool")

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def check_safe_path(relative_path: str) -> tuple[bool, str]:
    """Helper to check if path is safe (stays within workspace)."""
    abs_path = os.path.abspath(os.path.join(WORKSPACE_DIR, relative_path))
    if not abs_path.startswith(WORKSPACE_DIR):
        return False, "Error: Access denied. Path traversal outside workspace is blocked."
    return True, abs_path

@mcp.tool()
def read_pdf(filepath: str = None, page_number: int = None) -> str:
    """Extracts text from a local PDF file within the workspace.
    
    Args:
        filepath: Optional path of the PDF file to read. Defaults to 'data/quarterly_business_report.pdf'.
        page_number: Optional 0-indexed page number to extract. If omitted, extracts the entire PDF text.

    Returns:
        The extracted text as a string, or an error message.
    """
    target_path = filepath if filepath else "data/quarterly_business_report.pdf"
    is_safe, abs_path = check_safe_path(target_path)
    if not is_safe:
        return abs_path

    try:
        if not os.path.exists(abs_path):
            return f"Error: File '{filepath}' does not exist."
        if os.path.isdir(abs_path):
            return f"Error: '{filepath}' is a directory, not a PDF file."

        reader = PdfReader(abs_path)
        total_pages = len(reader.pages)

        if page_number is not None:
            if page_number < 0 or page_number >= total_pages:
                return f"Error: Invalid page number {page_number}. Total pages available: {total_pages} (0-indexed: 0 to {total_pages - 1})."
            
            text = reader.pages[page_number].extract_text()
            return f"--- Page {page_number + 1} of {total_pages} ---\n{text}"

        # Extract all text
        full_text = []
        for i, page in enumerate(reader.pages):
            full_text.append(f"--- Page {i + 1} of {total_pages} ---")
            full_text.append(page.extract_text() or "")
            
        return "\n".join(full_text)
    except Exception as e:
        return f"Error reading PDF file '{filepath}': {str(e)}"

if __name__ == "__main__":
    mcp.run()
