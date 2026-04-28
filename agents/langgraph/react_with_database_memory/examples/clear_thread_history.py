"""
Clear conversation history from PostgreSQL.
Set mode below: delete a single thread or wipe all threads.
"""

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from react_with_database_memory.utils import get_database_uri

load_dotenv()

# ============================================
# SET YOUR THREAD ID HERE
# Leave empty to delete ALL threads
# ============================================
thread_id = "YOUR_THREAD_ID"

DB_URI = get_database_uri()

if thread_id:
    # Delete a single thread
    with PostgresSaver.from_conn_string(DB_URI) as saver:
        saver.delete_thread(thread_id)
    print(f"Deleted thread: {thread_id}")

else:
    # Delete all threads
    with PostgresSaver.from_conn_string(DB_URI) as saver:
        count = 0
        seen = set()
        for cp_tuple in saver.list(None):
            tid = cp_tuple.config["configurable"]["thread_id"]
            if tid not in seen:
                seen.add(tid)

        for tid in seen:
            saver.delete_thread(tid)
            count += 1
            print(f"  Deleted: {tid}")

    print(f"\nDeleted {count} thread(s).")
