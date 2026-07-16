import sqlite3
import json
import time
import os
import hashlib  # Potrzebne do generowania bezpiecznych skrótów SHA-256
from models import AgentInput, AgentState
from typing import Dict, Any, List
from safety import SafetyLayer
from memory import MemoryModule
from groq import Groq

class PaxRuntime:
    def __init__(self, db_path: str = "storage.db"):
        self.db_path = db_path
        self.safety = SafetyLayer()
        self.memory = MemoryModule(db_path)
        
        # Klucz ze zmiennych środowiskowych
        api_key = os.environ.get("GROQ_API_KEY", "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")
        self.client = Groq(api_key=api_key)
        
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Tabela sesji (meta)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    title TEXT DEFAULT 'New Session',
                    created_at REAL,
                    updated_at REAL
                )
            """)
            
            # Tabela wiadomości (historia) z kolumnami previous_hash i current_hash
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT CHECK(role IN ('user', 'assistant')),
                    content TEXT,
                    embedding_hash TEXT,
                    safety_score REAL DEFAULT 0.0,
                    timestamp REAL,
                    previous_hash TEXT,
                    current_hash TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                )
            """)
            
            # --- AUTOMATYCZNA MIGRACJA DLA STARYCH BAZ ---
            # Sprawdzamy, czy w istniejącej tabeli messages brakuje nowych kolumn kryptograficznych
            cursor = conn.execute("PRAGMA table_info(messages)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "previous_hash" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN previous_hash TEXT;")
            if "current_hash" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN current_hash TEXT;")
                
            conn.commit()

    def _get_last_hash(self, conn, session_id: str) -> str:
        """Pobiera hash ostatniego wpisu w sesji. Jeśli to pierwszy wpis, zwraca Genesis Hash."""
        cursor = conn.execute("""
            SELECT current_hash FROM messages 
            WHERE session_id = ? 
            ORDER BY id DESC LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else "0" * 64

    def _calculate_hash(self, previous_hash: str, role: str, content: str, timestamp: float, session_id: str) -> str:
        """Generuje unikalny SHA-256 łączący poprzedni stan z nowymi danymi."""
        payload = f"{previous_hash}|{role}|{content}|{timestamp}|{session_id}"
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def verify_session_integrity(self, session_id: str) -> Dict[str, Any]:
        """
        BIZNESOWY AS W RĘKAWIE: Funkcja weryfikująca nienaruszalność logów.
        Przechodzi krok po kroku przez sesję i sprawdza, czy nikt nie modyfikował bazy.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT role, content, timestamp, previous_hash, current_hash 
                FROM messages 
                WHERE session_id = ? 
                ORDER BY id ASC
            """, (session_id,))
            rows = cursor.fetchall()
            
            if not rows:
                return {"status": "empty", "message": "Brak wiadomości w tej sesji do zweryfikowania."}
            
            expected_prev_hash = "0" * 64
            for i, (role, content, timestamp, prev_hash, curr_hash) in enumerate(rows):
                # Jeśli sprawdzamy stare wpisy sprzed migracji, które nie mają hasha – ignorujemy lub traktujemy jako niezweryfikowane
                if prev_hash is None or curr_hash is None:
                    return {
                        "status": "unverified", 
                        "message": "Sesja zawiera historyczne wpisy sprzed wdrożenia Audit Ledger. Nie można zweryfikować pełnej spójności."
                    }
                
                # 1. Czy poprzedni hash zgadza się z oczekiwanym?
                if prev_hash != expected_prev_hash:
                    return {
                        "status": "tampered", 
                        "error": f"Przerwany łańcuch na pozycji {i}. Oczekiwano: {expected_prev_hash}, otrzymano: {prev_hash}"
                    }
                
                # 2. Czy bieżący hash zgadza się z zawartością?
                calculated = self._calculate_hash(prev_hash, role, content, timestamp, session_id)
                if curr_hash != calculated:
                    return {
                        "status": "tampered", 
                        "error": f"Wykryto nieautoryzowaną modyfikację treści wpisu na pozycji {i}!"
                    }
                
                expected_prev_hash = curr_hash
                
            return {"status": "verified", "message": "Łańcuch jest nienaruszony. Dane są w 100% bezpieczne i autentyczne."}

    def process(self, input_data: AgentInput) -> Dict[str, Any]:
        # 1. REJESTRACJA I WERYFIKACJA BEZPIECZEŃSTWA
        with sqlite3.connect(self.db_path) as conn:
            now = time.time()
            session_data = {
                "session_id": input_data.session_id,
                "user_id": getattr(input_data, 'user_id', None),
                "title": f"Session {input_data.session_id}",
                "created_at": now,
                "updated_at": now
            }
            
            conn.execute("""
                INSERT OR REPLACE INTO sessions (session_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (input_data.session_id, session_data["user_id"], 
                  session_data["title"], session_data["created_at"], 
                  session_data["updated_at"]))
            
            # --- SEKCJA LEDGER: Generowanie hasha dla pytania użytkownika ---
            prev_hash = self._get_last_hash(conn, input_data.session_id)
            user_hash = self._calculate_hash(prev_hash, 'user', input_data.query, now, input_data.session_id)
            
            msg_id = conn.execute("""
                INSERT INTO messages (session_id, role, content, timestamp, safety_score, previous_hash, current_hash)
                VALUES (?, 'user', ?, ?, 0.0, ?, ?)
            """, (input_data.session_id, input_data.query, now, prev_hash, user_hash)).lastrowid
            
            # Wywołanie SafetyLayer
            safety_result = self.safety.check_query(input_data.query)
            
            conn.execute("""
                UPDATE messages SET safety_score = ? WHERE id = ?
            """, (safety_result['risk_score'], msg_id))
            conn.commit()
        
        # 🚫 BLOKADA WYSOKIEGO RYZYKA
        if not safety_result['cleared']:
            return {
                "status": "blocked",
                "risk_score": safety_result['risk_score'],
                "issues": safety_result['issues']
            }
        
        # 2. OPERACJE NA PAMIĘCI
        query_embedding = self.memory.embed_query(input_data.query)
        raw_memories = self.memory.find_similar(input_data.session_id, query_embedding)
        similar_memories = raw_memories if isinstance(raw_memories, list) else []
        self.memory.store_memory(input_data.session_id, input_data.query, query_embedding)
        
        # 3. KONSTRUKCJA KONTEKSTU DLA LLM
        if similar_memories:
            memories_context = "\n".join([f"- {mem['content']}" for mem in similar_memories])
            system_instruction = (
                "Jesteś pomocnym asystentem. Masz dostęp do powiązanych wspomnień "
                f"użytkownika, z których możesz i powinieneś skorzystać:\n{memories_context}"
            )
        else:
            system_instruction = "Jesteś pomocnym asystentem."

        # 4. WYWOŁANIE MODELU (Groq)
        try:
            completion = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": input_data.query}
                ],
                temperature=0.7
            )
            response = completion.choices[0].message.content
        except Exception as e:
            response = f"Przepraszam, wystąpił problem z Groq: {str(e)}"
        
        # 5. ZAPIS ODPOWIEDZI ASYSTENTA (Osobna transakcja z HCAL)
        with sqlite3.connect(self.db_path) as conn:
            now_assistant = time.time()
            prev_hash_assistant = self._get_last_hash(conn, input_data.session_id)
            assistant_hash = self._calculate_hash(prev_hash_assistant, 'assistant', response, now_assistant, input_data.session_id)
            
            conn.execute("""
                INSERT INTO messages (session_id, role, content, timestamp, safety_score, previous_hash, current_hash)
                VALUES (?, 'assistant', ?, ?, 0.0, ?, ?)
            """, (input_data.session_id, response, now_assistant, prev_hash_assistant, assistant_hash))
            conn.commit()
        
        return {
            "status": "processed",
            "response": response,
            "safety": safety_result,
            "memories_found": len(similar_memories),
            "top_memory": similar_memories[0] if similar_memories else None,
            "session_id": input_data.session_id
        }