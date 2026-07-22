from langchain_core.tools import tool
from pydantic import BaseModel, Field


class AccountInput(BaseModel):
    """Schema for the account balance tool input."""

    account_id: str = Field(description="The customer account ID to look up.")


@tool("check_balance", parse_docstring=True)
def check_account_balance(account_id: str) -> str:
    """Check the account balance for a bank customer.

    Placeholder implementation that returns a fixed balance for demonstration.
    Replace with a real banking API integration in production.

    Args:
        account_id: The customer account ID. Example: "ACCT-12345"

    Returns:
        A string with the account balance information.
    """
    return (
        f"Account {account_id}: Checking balance $2,450.00, "
        f"Savings balance $12,800.50. Last transaction: -$45.99 on 2026-07-20."
    )
