"""Semantic search across reflections, videos, and searches."""

from fastapi import APIRouter, HTTPException, Query
from api.vec import embed_query, search_table
from embed_common import ALL_TABLES

router = APIRouter(prefix="/api/search", tags=["search"])

TableChoice = str  # validated below


@router.get("")
def semantic_search(
    q: str = Query(..., min_length=1, description="Natural language query"),
    table: str | None = Query(None, description="One of: reflections, videos, searches. Omit for all."),
    top: int = Query(10, ge=1, le=50),
):
    if table is not None and table not in ALL_TABLES:
        raise HTTPException(status_code=422, detail=f"table must be one of {ALL_TABLES}")

    tables_to_search = [table] if table else ALL_TABLES

    vector = embed_query(q)

    results = {}
    for t in tables_to_search:
        results[t] = search_table(t, vector, top=top)

    return {"query": q, "results": results}
