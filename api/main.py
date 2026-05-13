"""Echo API — FastAPI app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import timeline, chapters, search, diff, chat

app = FastAPI(title="Echo API", version="0.1.0")

# Dev: Vite proxy handles /api → :8000, so no CORS needed in production.
# This permissive config is for curl/Postman testing during development only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(timeline.router)
app.include_router(chapters.router)
app.include_router(search.router)
app.include_router(diff.router)
app.include_router(chat.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
