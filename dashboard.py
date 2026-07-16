from fastapi import APIRouter, HTTPException
import sqlite3
from typing import List, Dict

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/sessions")
async def list_sessions() -> List[Dict]:
    conn = sqlite3.connect("storage.db")
    conn.row_factory = sqlite3.Row
    
    # Użyliśmy LEFT JOIN na wypadek, gdyby sesja istniała, ale nie miała jeszcze wiadomości
    sessions = conn.execute("""
        SELECT 
            s.session_id,
            COUNT(m.id) as queries,
            MAX(m.timestamp) as last_seen,
            s.title,
            AVG(m.safety_score) as avg_safety
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.session_id
        GROUP BY s.session_id
    """).fetchall()
    
    conn.close()
    
    result = []
    for s in sessions:
        # Zabezpieczenie przed None w avg_safety i last_seen
        safety_val = s["avg_safety"] if s["avg_safety"] is not None else 0.0
        last_val = str(s["last_seen"]) if s["last_seen"] is not None else "brak aktywności"
        
        result.append({
            "id": s["session_id"], 
            "queries": s["queries"], 
            "last": last_val, 
            "title": s["title"] or "Brak tytułu",
            "safety": round(safety_val, 2)
        })
    return result

@router.get("/sessions/{session_id}")
async def session_details(session_id: str) -> List[Dict]:
    conn = sqlite3.connect("storage.db")
    conn.row_factory = sqlite3.Row
    
    history = conn.execute("""
        SELECT role, content, timestamp, safety_score,
               embedding_hash IS NOT NULL as has_memory
        FROM messages WHERE session_id = ? 
        ORDER BY timestamp ASC
    """, (session_id,)).fetchall()
    
    conn.close()
    
    if not history:
        raise HTTPException(status_code=404, detail="Nie znaleziono wiadomości dla tej sesji")
        
    return [{
        "role": h["role"], 
        "content": h["content"][:100] + "..." if len(h["content"]) > 100 else h["content"],
        "timestamp": str(h["timestamp"]), 
        "safety": h["safety_score"] if h["safety_score"] is not None else 0.0,
        "memory": bool(h["has_memory"])
    } for h in history]

@router.get("/sessions/{session_id}/memory")
async def session_memory(session_id: str) -> Dict:
    """Pokazuje top podobne wiadomości z sesji"""
    conn = sqlite3.connect("storage.db")
    conn.row_factory = sqlite3.Row
    
    recent = conn.execute("""
        SELECT content, role, timestamp
        FROM messages 
        WHERE session_id = ? AND embedding_hash IS NOT NULL
        ORDER BY timestamp DESC LIMIT 10
    """, (session_id,)).fetchall()
    
    conn.close()
    return {"session_id": session_id, "memories": [dict(r) for r in recent]}

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> Dict:
    """Usuwa sesję oraz wszystkie powiązane wiadomości z bazy"""
    conn = sqlite3.connect("storage.db")
    
    # 1. Usuwamy wiadomości z tej sesji
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    # 2. Usuwamy samą sesję
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    
    conn.commit()
    conn.close()
    
    return {"status": "deleted", "session_id": session_id, "message": "Wyczyszczono historię i sesję."}