from langgraph.checkpoint.postgres import PostgresSaver
from langgraph_react_with_database_memory_base.utils import get_database_uri

thread_id = "PLACEHOLDER FOR YOUR THREAD ID"

# Get database URI from environment variables
DB_URI = get_database_uri()

# Delete the thread from the database
with PostgresSaver.from_conn_string(DB_URI) as saver:
    saver.delete_thread(thread_id)

print(f"Successfully deleted conversation with id: {thread_id}")
