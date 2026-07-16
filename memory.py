from sentence_transformers import SentenceTransformer
from typing import List, Dict
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from datetime import datetime
import sqlite3
import json

class MemoryModule:
    def __init__(self, db_path: str = "storage.db"):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.db_path = db_path
        
    def embed_query(self, query: str) -> np.ndarray:
        """Zamień query na vector"""
        return self.model.encode(query)
    
    def store_memory(self, session_id: str, query: str, embedding: np.ndarray):
        """Zapisz EMBEDDING do DB"""
        conn = sqlite3.connect(self.db_path)
        embedding_json = json.dumps(embedding.tolist())
        
        conn.execute("""
            UPDATE messages 
            SET embedding_hash = ? 
            WHERE id = (SELECT MAX(id) FROM messages WHERE session_id = ?)
        """, (embedding_json, session_id))
        
        conn.commit()
        conn.close()
    
    def find_similar(self, session_id: str, query_embedding: np.ndarray, top_k: int = 3) -> List[Dict]:
        """Znajdź podobne z tej sesji"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # Pobierz embeddingi z sesji
        rows = conn.execute("""
            SELECT content, embedding_hash, timestamp, role
            FROM messages 
            WHERE session_id = ? AND embedding_hash IS NOT NULL
            ORDER BY timestamp DESC LIMIT 50
        """, (session_id,)).fetchall()
        
        similarities = []
        for row in rows:
            try:
                mem_embedding = np.array(json.loads(row['embedding_hash']))
                sim = cosine_similarity([query_embedding], [mem_embedding])[0][0]
                similarities.append({
                    'similarity': float(sim),
                    'content': row['content'],
                    'role': row['role'],
                    'timestamp': row['timestamp']
                })
            except:
                continue
        
        conn.close()
        return sorted(similarities, key=lambda x: x['similarity'], reverse=True)[:top_k]
