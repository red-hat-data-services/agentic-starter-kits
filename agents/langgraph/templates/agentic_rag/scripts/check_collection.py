#!/usr/bin/env python3
"""Check if Milvus collection exists and show basic info."""
import os

from pymilvus import Collection, connections, utility

milvus_uri = os.getenv("MILVUS_URI")
milvus_token = os.getenv("MILVUS_TOKEN")
milvus_cert = os.getenv("MILVUS_SERVER_CERT")
collection_name = os.getenv("MILVUS_COLLECTION_NAME")

# Parse URI properly for both http:// and https://
secure = milvus_uri.startswith("https://")
uri_without_scheme = milvus_uri.replace("https://", "").replace("http://", "")
host = uri_without_scheme.split(":")[0]
port = uri_without_scheme.split(":")[-1].split("/")[0]  # Remove any path after port
user, password = milvus_token.split(":")

connections.connect(
    alias="default",
    host=host,
    port=port,
    user=user,
    password=password,
    secure=secure,
    server_pem_path=milvus_cert if secure else None,
)

collections = utility.list_collections()

if collection_name in collections:
    col = Collection(collection_name)
    col.flush()
    col.load()
    num = col.num_entities
    print(f"✅ Collection found: {collection_name}")
    print(f"   Entities: {num}")
    print(f"   Schema fields: {[f.name for f in col.schema.fields]}")
    if num == 0:
        stats = col.get_replicas()
        print(f"   Replicas: {stats}")
        try:
            results = col.query(expr="", limit=5, output_fields=["chunk_id", "content"])
            print(f"   Query returned: {len(results)} rows")
            for r in results[:3]:
                print(f"     - {r.get('chunk_id', '?')}: {str(r.get('content', ''))[:80]}")
        except Exception as e:
            print(f"   Query error: {e}")
else:
    print(f"❌ Collection not found: {collection_name}")
    print(f"   Available collections: {len(collections)}")

connections.disconnect("default")
