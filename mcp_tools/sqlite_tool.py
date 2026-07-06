import sqlite3
import os
from mcp.server.fastmcp import FastMCP

# Define the FastMCP server
mcp = FastMCP("SQLite Tool")

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "business_data.db"))

@mcp.tool()
def run_query(sql_query: str, db_path: str = None) -> str:
    """Runs a read-only SQL query on the SQLite database of business KPIs.
    
    The database contains a 'kpis' table with the following schema:
    - Quarter: TEXT (e.g. '2026-Q2')
    - Revenue: INTEGER (total revenue in dollars)
    - Expenses: INTEGER (total operating expenses in dollars)
    - Marketing_Spend: INTEGER (marketing spend in dollars)
    - CAC: INTEGER (Customer Acquisition Cost in dollars)
    - LTV: INTEGER (Customer Lifetime Value in dollars)
    - Risk_Score: REAL (a value between 0.0 and 1.0)
    - Compliance_Status: TEXT ('Compliant' or 'Non-Compliant')

    Only SELECT queries are permitted. Modifying operations are blocked.

    Args:
        sql_query: The SQL SELECT query to run (e.g., 'SELECT Quarter, Revenue, Expenses FROM kpis WHERE Quarter = "2026-Q2"').
        db_path: Optional path to a specific SQLite database to query. If not provided, defaults to the standard database.

    Returns:
        The query results as a formatted string (typically representation of records), or an error message.
    """
    # Quick sanity check for safety
    query_clean = sql_query.strip().lower()
    
    # Simple block list for destructive operations
    blocked_keywords = ["insert", "update", "delete", "drop", "alter", "create", "replace", "truncate", "vacuum"]
    for keyword in blocked_keywords:
        if keyword in query_clean:
            return f"Error: Command denied. Modifying keyword '{keyword}' detected. Only read-only SELECT queries are allowed."
            
    if not query_clean.startswith("select"):
        return "Error: Command denied. Only SELECT statements are permitted."

    target_db = os.path.abspath(db_path) if db_path else DB_PATH

    if not os.path.exists(target_db):
        return f"Error: Database file does not exist at {target_db}. Please check database configuration."

    conn = sqlite3.connect(target_db)
    try:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        
        if not rows:
            return "No records found."
            
        # Format as list of dicts string representation
        results = []
        for row in rows:
            results.append(dict(zip(columns, row)))
        return str(results)
    except Exception as e:
        return f"Error executing SQL query: {str(e)}"
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run()
