from qdrant_client import QdrantClient
from qdrant_client.http import models

def init_local_qdrant_db():
    print("Initializing Qdrant Vector Store on local NVMe...")
    # This stores the vectors locally on the drone's SSD/NVMe
    client = QdrantClient(path="local_qdrant_db") 
    
    collection_name = "stead_medoids"
    
    # Creating a single collection holding 512-dim spatial and temporal embeddings
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE),
    )
    
    print(f"Created Qdrant collection: {collection_name}")
    print("Database is ready to receive Tier 1, 2, and 3 embedded Medoids.")
    
if __name__ == "__main__":
    init_local_qdrant_db()
