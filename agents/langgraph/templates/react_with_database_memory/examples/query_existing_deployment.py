"""
Query PostgreSQL checkpoint database to inspect stored conversation messages.
Set thread_id below and run the script.
"""

from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres import PostgresSaver
from react_with_database_memory.utils import get_database_uri

load_dotenv()

# ============================================
# SET YOUR THREAD ID HERE
# Leave empty to list all available threads
# ============================================
thread_id = "YOUR_THREAD_ID"

DB_URI = get_database_uri()

if not thread_id:
    # List all threads so you can pick one
    print("\nNo thread_id set — listing all threads:\n")
    with PostgresSaver.from_conn_string(DB_URI) as saver:
        seen = set()
        for cp_tuple in saver.list(None, limit=50):
            tid = cp_tuple.config["configurable"]["thread_id"]
            if tid not in seen:
                seen.add(tid)
                msgs = cp_tuple.checkpoint.get("channel_values", {}).get("messages", [])
                preview = ""
                for m in msgs:
                    if hasattr(m, "content") and m.content:
                        preview = m.content[:60]
                        break
                print(f"  {tid}  ({len(msgs)} msgs)  {preview}")

    print(f"\n{len(seen)} thread(s) found.")
    print('Set thread_id = "..." in the script and re-run to see messages.')

else:
    # Show all messages for the given thread
    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(DB_URI) as saver:
        cp_tuple = saver.get_tuple(config)

    if not cp_tuple or not cp_tuple.checkpoint:
        print(f"No checkpoint found for thread '{thread_id}'")
    else:
        messages = cp_tuple.checkpoint.get("channel_values", {}).get("messages", [])

        print(f"\nThread: {thread_id}")
        print(f"Total messages: {len(messages)}")
        print("=" * 70)

        for i, msg in enumerate(messages):
            role = type(msg).__name__.replace("Message", "").lower()
            content = msg.content if msg.content else ""
            if isinstance(msg, AIMessage) and msg.tool_calls:
                calls = ", ".join(tc["name"] for tc in msg.tool_calls)
                content = content or f"[tool_calls: {calls}]"
            print(f"[{i + 1:3d}] {role:9s} | {content}")

        print("=" * 70)
