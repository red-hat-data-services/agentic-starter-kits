import asyncio
from utils import PersonInformation
from mcp.server.fastmcp import FastMCP

# Create an MCP server (OpenAI-based; credit risk scoring can be added via your own backend)
mcp = FastMCP("AutoMl Credit Risk", log_level="ERROR")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


@mcp.tool()
def sub(a: int, b: int) -> int:
    """Subtract two numbers"""
    return a - b


@mcp.tool()
def evaluate_credit_risk(person_information: PersonInformation) -> dict:
    """Evaluate credit risk based on person information (demo stub).

    Fill person_information with the possible inputs defined in PersonInformation.
    This is a placeholder that returns a simple risk score; replace with your own
    scoring backend (e.g. local model or API) as needed.
    """
    # Demo: return a placeholder structure; integrate your own scoring logic here
    return {
        "risk_score": 0.5,
        "message": "Credit risk evaluation stub. Replace with your scoring backend (e.g. OpenAI or custom API).",
        "input_summary": {
            "LoanAmount": person_information.LoanAmount,
            "CreditHistory": person_information.CreditHistory,
        },
    }


if __name__ == "__main__":
    asyncio.run(mcp.run_sse_async())
