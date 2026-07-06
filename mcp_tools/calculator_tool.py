import ast
import operator
import sys
from mcp.server.fastmcp import FastMCP

# Define the FastMCP server
mcp = FastMCP("Calculator Tool")

# Safe math operators mapping
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

def safe_eval(node):
    """Recursively evaluates AST nodes safely."""
    if isinstance(node, ast.Num):
        return node.n
    elif isinstance(node, ast.Constant):  # For newer Python versions
        if isinstance(node.value, (int, float)):
            return node.value
        raise TypeError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.BinOp):
        left = safe_eval(node.left)
        right = safe_eval(node.right)
        op_type = type(node.op)
        if op_type in OPERATORS:
            return OPERATORS[op_type](left, right)
        raise TypeError(f"Unsupported binary operator: {op_type}")
    elif isinstance(node, ast.UnaryOp):
        operand = safe_eval(node.operand)
        op_type = type(node.op)
        if op_type in OPERATORS:
            return OPERATORS[op_type](operand)
        raise TypeError(f"Unsupported unary operator: {op_type}")
    else:
        raise TypeError(f"Unsupported AST node: {type(node)}")

@mcp.tool()
def calculate(expression: str) -> str:
    """Safely evaluates a mathematical expression.
    
    Args:
        expression: The mathematical expression to evaluate (e.g., '2.5 * (1200000 - 850000) / 100').
        
    Returns:
        The result of the calculation as a string, or an error message.
    """
    try:
        # Clean input
        clean_expr = expression.replace(" ", "")
        # Parse expression to AST
        tree = ast.parse(clean_expr, mode='eval')
        result = safe_eval(tree.body)
        return str(result)
    except Exception as e:
        return f"Error evaluating expression '{expression}': {str(e)}"

@mcp.tool()
def calculate_roi(revenue: float, cost: float) -> str:
    """Calculates Return on Investment (ROI) percentage.
    
    Formula: ((Revenue - Cost) / Cost) * 100
    
    Args:
        revenue: The projected or actual financial return/revenue.
        cost: The initial investment or cost.
        
    Returns:
        The ROI as a formatted percentage string.
    """
    if cost == 0:
        return "Error: Cost cannot be zero."
    try:
        roi = ((revenue - cost) / cost) * 100
        return f"ROI: {roi:.2f}%"
    except Exception as e:
        return f"Error calculating ROI: {str(e)}"

@mcp.tool()
def calculate_cagr(start_val: float, end_val: float, periods: int) -> str:
    """Calculates Compound Annual Growth Rate (CAGR) percentage.
    
    Formula: ((End Value / Start Value) ** (1 / Periods) - 1) * 100
    
    Args:
        start_val: The initial value at the start of the period.
        end_val: The final value at the end of the period.
        periods: Number of compounding periods (usually years).
        
    Returns:
        The CAGR as a formatted percentage string.
    """
    if start_val <= 0 or end_val <= 0:
        return "Error: Start and end values must be positive numbers."
    if periods <= 0:
        return "Error: Compounding periods must be greater than zero."
    try:
        cagr = ((end_val / start_val) ** (1 / periods) - 1) * 100
        return f"CAGR: {cagr:.2f}%"
    except Exception as e:
        return f"Error calculating CAGR: {str(e)}"

@mcp.tool()
def calculate_payback_period(initial_investment: float, annual_cash_flow: float) -> str:
    """Calculates payback period in years.
    
    Formula: Initial Investment / Annual Cash Flow
    
    Args:
        initial_investment: The initial capital expenditure.
        annual_cash_flow: The expected annual positive cash flow generated.
        
    Returns:
        The payback period in years as a formatted string.
    """
    if annual_cash_flow <= 0:
        return "Error: Annual cash flow must be a positive number."
    try:
        years = initial_investment / annual_cash_flow
        return f"Payback Period: {years:.2f} years"
    except Exception as e:
        return f"Error calculating payback period: {str(e)}"

if __name__ == "__main__":
    mcp.run()
