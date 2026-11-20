"""Navoiyazot Logistics: Repair Assistant Service."""
import logging
import uvicorn
from fastapi import FastAPI
from repair_assistant.router import router as repair_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="Navoiyazot Logistics · Repair Assistant API",
    description="Data-driven repair duration estimation (ETA) and structured mechanic diagnostic checklists for Navoiyazot.",
    version="1.0.0"
)

app.include_router(repair_router)

@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "repair-assistant"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=False)
