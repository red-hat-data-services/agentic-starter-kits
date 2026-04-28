import asyncio
import textwrap
from os import getenv

from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession
from mcp.client.sse import sse_client
from utils import get_chat_from_env

# LLM from .env: BASE_URL, MODEL_ID, API_KEY (see repo template.env; Ollama example there)
chat_openai = get_chat_from_env()

# Dictionary of predefined questions with descriptions
questions = {
    "Simple addition": "What is 1+1?",
    "Subtraction example": "What is 100-1?",
    "Churn - low risk profile": """Will this customer churn? Female, not a senior citizen, has a partner and no dependents. Tenure 24 months, has phone service and multiple lines. Internet: DSL, with online security and backup. Contract: Two year. Paperless billing yes, payment by credit card. Monthly charges 65, total charges 1560.""",
    "Churn - higher risk profile": """Predict churn for this customer: Male, senior citizen (1), no partner, no dependents. Tenure 3 months, phone service yes, no multiple lines. Fiber optic internet, no online security or backup. Contract: Month-to-month. Paperless billing yes, electronic check. Monthly charges 89, total charges 267.""",
}

# Help message
help_message = textwrap.dedent(
    """\nThe following commands are supported:
  --> help | h : prints this help message
  --> quit | q : exits the prompt and ends the program
  --> list_questions | lq : prints a list of available questions"""
)


# Function to send a query to the agent
async def ask_question(agent, user_input: str):
    response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": user_input}]}
    )
    for msg in response["messages"]:
        msg.pretty_print()


# Main chat loop
async def chat_loop():
    mcp_url = getenv("MCP_SERVER_URL", "http://127.0.0.1:8080/sse")
    print(mcp_url)
    async with sse_client(url=mcp_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            formatted_tools = tools

            # System prompt for Llama 3.1 8B: only use tools if truly necessary, otherwise answer directly.
            # For increased agency, guide the model to avoid tool use unless it cannot answer from its own knowledge.
            # The system prompt for Llama 3.1 8B should specifically instruct the model to do two things:
            # 1. If a tool is used and a response is returned as a list of objects containing a 'text' field,
            #    extract the answer from the 'text' field and present that as the final user-facing response.
            # 2. Always ensure that the user receives a direct, clear answer to their question, whether from the model's own knowledge or from an extracted tool response.
            system_prompt = (
                "You are a helpful assistant. Your goal is to answer the user's question directly in every interaction. "
                "ONLY call a tool if you cannot answer with your own knowledge or if external/up-to-date information is required. "
                "If you call a tool (python) and receive a response in the format [{'type': 'text', 'text': '...', 'id': ...}], "
                "you MUST extract the value of the 'text' field from the response and present it as your FINAL answer to the user. "
                "Never call tools more than once for the same user question. You must reply with a clear, direct answer based either on your knowledge or on the result extracted from the 'text' field of a tool response. "
                "Be polite, concise, and accurate in every reply."
            )

            agent = create_react_agent(
                chat_openai, formatted_tools, prompt=system_prompt
            )

            print(help_message)

            # Convert to list for indexed access
            question_items = list(questions.items())

            while True:
                try:
                    user_input = input(
                        "\nChoose a question or ask one of your own.\n --> "
                    ).strip()
                    cmd = user_input.lower()

                    if cmd in ["quit", "q"]:
                        break

                    elif cmd in ["help", "h"]:
                        print(help_message)
                        continue

                    elif cmd in ["list_questions", "lq"]:
                        print("\n📋 List of predefined questions:\n")
                        for i, (desc, q) in enumerate(question_items, start=1):
                            print(f'{i}. {desc} → "{q}"')
                        continue

                    elif user_input.isdigit():
                        idx = int(user_input)
                        if 1 <= idx <= len(question_items):
                            desc, q = question_items[idx - 1]
                            print(f"\n🟢 Sending question {idx} ({desc}): {q}")
                            await ask_question(agent, q)
                        else:
                            print("\n⚠️ Invalid question number.")
                        continue

                    await ask_question(agent, user_input)

                except Exception as e:
                    print(f"[ERROR] {e}")
                    break


if __name__ == "__main__":
    asyncio.run(chat_loop())
