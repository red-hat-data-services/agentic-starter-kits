"""
Run the Human-in-the-Loop agent locally with an interactive chat loop.

When the agent wants to call create_file, the HumanInTheLoopMiddleware
fires an interrupt and the graph pauses. This script detects the pause,
shows the pending tool call, asks for approval, and resumes with
Command(resume={"decisions": [{"type": "approve"|"reject"}]}).

Usage:
    cd agents/langgraph/human_in_the_loop
    source ./init.sh
    uv pip install -e .
    uv run examples/execute_ai_service_locally.py
"""

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from os import getenv

from human_in_the_loop.agent import get_graph_closure
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command


def main():
    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")

    if not base_url or not model_id:
        print("ERROR: BASE_URL and MODEL_ID must be set. Run: source ./init.sh")
        sys.exit(1)

    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    print(f"Connecting to LLM: {base_url} (model: {model_id})\n")

    graph_closure = get_graph_closure(model_id=model_id, base_url=base_url)
    checkpointer = MemorySaver()
    agent = graph_closure(checkpointer)

    thread_counter = 0

    help_message = textwrap.dedent("""
    The following commands are supported:
      --> help | h : prints this help message
      --> quit | q : exits the prompt and ends the program

    Try asking: "Create a file called report.md with info about LangChain"
    Or just say: "Hello, how are you?"
    """)
    print(help_message)

    while True:
        try:
            user_input = input("\n --> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input in ("h", "help"):
            print(help_message)
            continue
        if user_input in ("q", "quit"):
            break

        # Fresh thread for each question
        thread_counter += 1
        config = {"configurable": {"thread_id": f"local-{thread_counter}"}}

        # Invoke the agent with version="v2" to get GraphOutput with interrupts
        result = agent.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            version="v2",
        )

        if result.interrupts:
            # Graph paused — HumanInTheLoopMiddleware wants approval
            interrupt = result.interrupts[0]
            interrupt_data = interrupt.value

            print(f"\n{'  Approval Required  ':=^60}")

            action_requests = interrupt_data.get("action_requests", [])
            for action in action_requests:
                print(f"\n  Tool: {action['name']}")
                args = action.get("args", {})
                for key, value in args.items():
                    display_val = str(value)
                    if len(display_val) > 120:
                        display_val = display_val[:120] + "..."
                    print(f"    {key}: {display_val}")

            approval = input("\n  >>> Approve? (yes/no): ").strip().lower()

            if approval in ("yes", "y"):
                # Resume with approve decision
                result = agent.invoke(
                    Command(resume={"decisions": [{"type": "approve"}]}),
                    config=config,
                    version="v2",
                )
            else:
                # Resume with reject decision
                result = agent.invoke(
                    Command(
                        resume={
                            "decisions": [
                                {
                                    "type": "reject",
                                    "message": "User rejected the tool call.",
                                }
                            ]
                        }
                    ),
                    config=config,
                    version="v2",
                )

        # Print the final response
        messages = (
            result.value.get("messages", [])
            if hasattr(result, "value")
            else result.get("messages", [])
        )
        for msg in messages:
            if isinstance(msg, ToolMessage):
                print(f"\n{'  Tool Result  ':=^60}")
                print(f"  {msg.content}")
            elif isinstance(msg, AIMessage) and msg.content:
                if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                    print(f"\n{'  Assistant  ':=^60}")
                    print(f"  {msg.content}")


if __name__ == "__main__":
    main()
