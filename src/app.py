"""HTTP surface. Phase 3: /retrieve only (no LLM). incident_date is accepted and echoed
but does not change retrieval yet: date routing (IPC vs BNS) is Phase 4."""
import dataclasses

from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.retrieve import citation, retrieve

app = FastAPI(title="statute-finder-india")

DISCLAIMER = "Informational, not legal advice."


class RetrieveRequest(BaseModel):
    incident: str = Field(min_length=3, max_length=2000)
    incident_date: str | None = None          # echoed only; routing happens in /analyze
    mode: str = "hybrid"
    k_per_act: int = Field(3, ge=1, le=10)
    k_final: int = Field(8, ge=1, le=30)


@app.post("/retrieve")
async def retrieve_endpoint(req: RetrieveRequest):
    hits = await retrieve(req.incident, k_per_act=req.k_per_act, k_final=req.k_final, mode=req.mode)
    return {
        "incident": req.incident,
        "incident_date": req.incident_date,
        "date_routing": "not applied here; use /analyze",
        "results": [dict(dataclasses.asdict(h), citation=citation(h)) for h in hits],
        "disclaimer": DISCLAIMER,
    }


class AnalyzeRequest(BaseModel):
    incident: str = Field(min_length=3, max_length=2000)
    incident_date: str | None = None          # ISO date; overrides any date in the text
    k_per_act: int = Field(3, ge=1, le=10)
    k_final: int = Field(8, ge=1, le=30)


@app.post("/answer")
async def answer_endpoint(req: AnalyzeRequest):
    """Phase 5: facts + routing + retrieval + validated selection/grouping or abstention."""
    from src.answer import answer

    return await answer(req.incident, req.incident_date)


@app.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest):
    from src.analyze import analyze

    return await analyze(req.incident, req.incident_date, k_per_act=req.k_per_act, k_final=req.k_final)


# ---- demo surface (decision 46) ----------------------------------------------------------
import os  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402

_INDEX = os.path.join(os.path.dirname(__file__), "static", "index.html")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(_INDEX, media_type="text/html")


def _build_marker() -> str:
    """Newest modification time among src/ files at process start: shows which code a server runs."""
    import datetime as dt
    import glob

    root = os.path.dirname(__file__)
    files = glob.glob(os.path.join(root, "*.py")) + glob.glob(os.path.join(root, "static", "*"))
    return dt.datetime.fromtimestamp(max(os.path.getmtime(f) for f in files)).strftime("%Y-%m-%d %H:%M")


_STARTED_BUILD = _build_marker()   # captured at import = the code this process actually loaded


@app.get("/health")
async def health():
    return {"status": "ok", "build": _STARTED_BUILD}


@app.get("/page-image")
async def page_image(chunk_id: int):
    """PNG of the cited PDF page with the quoted lines highlighted. The file and offsets
    come from the database row for `chunk_id`, never from the request."""
    import asyncio

    from src.pageimage import chunk_source, pdf_path, render_highlight

    src = await chunk_source(chunk_id)
    if src is None:
        raise HTTPException(status_code=404, detail="unknown chunk")
    png, page = await asyncio.to_thread(render_highlight, pdf_path(src["filename"]), src["segments"], src["text"])
    return Response(content=png, media_type="image/png", headers={"X-Source-Page": str(page),
                                                                  "Cache-Control": "public, max-age=3600"})
