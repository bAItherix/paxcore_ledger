from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
from runtime import PaxRuntime
from models import AgentInput
from typing import Optional, Dict, Any
from datetime import datetime
from dashboard import router as dashboard_router  # OK

app = FastAPI(title="PaxCore v0.1")  # ← Najpierw app!
app.include_router(dashboard_router)  # ← Potem router!
runtime = PaxRuntime()  # ← Na końcu runtime (potrzebuje DB)


class Input(BaseModel):
    query: str
    session_id: str = "default"

@app.post("/debug_process")
async def debug_process(input: Input):  # ← zmień nazwę funkcji!
    return {
        "status": "ok", 
        "output": f"🟢 Processed: {input.query}",
        "session_id": input.session_id
    }

@app.post("/process")
async def process(input_data: AgentInput):
    result = runtime.process(input_data)
    return {
        "status": "processed",
        "result": result,
        "session_id": input_data.session_id
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
