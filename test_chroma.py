import chromadb
import os

path = os.path.join("memory", "test_chroma")
os.makedirs(path, exist_ok=True)

try:
    client = chromadb.PersistentClient(path=path)
    collection = client.get_or_create_collection(name="test")
    collection.add(
        documents=["This is a test document"],
        metadatas=[{"source": "test"}],
        ids=["id1"]
    )
    results = collection.query(
        query_texts=["test"],
        n_results=1
    )
    print(f"Success! Results: {results}")
except Exception as e:
    print(f"ChromaDB error: {e}")
