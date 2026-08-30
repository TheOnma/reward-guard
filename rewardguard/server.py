"""FastAPI server for the Judge-vs-Verifier demo page.

Endpoints:
  GET  /                  -> the demo page (web/index.html)
  POST /judge             -> baseline naive judge verdict (JSON)
  POST /verify_stream     -> RewardGuard verifier, streamed step-by-step (SSE)

Set MOCK=1 in the environment to run the demo with no API keys.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .config import settings
from .judges import baseline_judge, reward_guard_verify

app = FastAPI(title="RewardGuard")
MOCK = os.environ.get("MOCK", "0") == "1"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return WEB.read_text()


@app.post("/judge")
async def judge(req: Request) -> JSONResponse:
    body = await req.json()
    label = baseline_judge(body["prompt"], body["reference"], body["candidate"], mock=MOCK)
    return JSONResponse({"label": label})


@app.post("/verify_stream")
async def verify_stream(req: Request) -> StreamingResponse:
    body = await req.json()

    def gen():
        verdict = reward_guard_verify(body["prompt"], body["reference"], body["candidate"], mock=MOCK)
        for step in verdict.steps:
            yield f"event: step\ndata: {json.dumps(step)}\n\n"
        yield f"event: verdict\ndata: {json.dumps({'label': verdict.label, 'reason': verdict.reason})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
