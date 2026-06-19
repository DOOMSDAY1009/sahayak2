"""
KaryaSetu NLP API — the backbone every other piece plugs into.
==============================================================
Endpoints:
  GET  /                health + Bhashini status
  GET  /services        list everything KaryaSetu offers
  POST /match           text  -> matched service  (WORKS NOW)
  POST /voice/match     audio -> ASR -> match -> TTS  (works once Bhashini keys are set)

Run:
    uvicorn app:app --reload
Docs (try it in the browser):
    http://127.0.0.1:8000/docs
"""

import base64
import os
from typing import Any, Dict, List

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bhashini
from catalog_store import store
from matcher import match_service, active_model

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="KaryaSetu NLP", version="0.1")

# allow the voice webpage (and the app team's frontend) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# seed the LIVE catalog from the bundled JSON at startup. The app keeps it
# up to date afterwards via POST /catalog/sync (see below).
store.load_file(os.path.join(BASE_DIR, "service_catalog.json"))


# ---- schemas -------------------------------------------------------
class MatchRequest(BaseModel):
    text: str
    use_fast_path: bool = False
    reply_language: str | None = None   # answer in THIS language (e.g. "English")


class CatalogSync(BaseModel):
    services: List[Dict[str, Any]]   # the app's current service list


# ---- endpoints -----------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm": active_model(),
        "services_loaded": len(store.get()),
        "voice_ready": bhashini.is_configured,
        "voice_note": None if bhashini.is_configured
        else "Set BHASHINI_USER_ID and BHASHINI_API_KEY to enable voice.",
    }


@app.get("/services")
def list_services():
    """The services the engine currently knows about (the live catalog)."""
    return store.as_list()


@app.post("/catalog/sync")
def catalog_sync(payload: CatalogSync):
    """
    The app calls this whenever its services change (add/edit/remove).
    Send the FULL current list; the engine replaces its catalog and starts
    matching against it immediately. This is what keeps Sahayak auto-updated.
    """
    count = store.set_services(payload.services)
    return {"synced": True, "services_loaded": count}


@app.post("/match")
def match(req: MatchRequest):
    """Core endpoint: a complaint in ANY language -> grounded service match.
    Always matches against the LIVE catalog (whatever the app last synced)."""
    try:
        return match_service(req.text, store.get(),
                             use_fast_path=req.use_fast_path,
                             reply_language=req.reply_language)
    except Exception as e:
        # surface the real reason (e.g. bad/missing OpenAI key) in the response
        return JSONResponse(
            status_code=500,
            content={"error": type(e).__name__, "detail": str(e)},
        )


@app.post("/voice/match")
async def voice_match(audio: UploadFile = File(...), lang: str = Form("hi")):
    """
    Full voice loop:  🎤 audio -> ASR -> match -> TTS -> 🔊 audio reply.
    Returns the structured match PLUS a base64 WAV the app can play back.
    """
    if not bhashini.is_configured:
        return JSONResponse(
            status_code=503,
            content={"error": "Bhashini not configured.",
                     "fix": "Set BHASHINI_USER_ID and BHASHINI_API_KEY, then retry."},
        )

    audio_bytes = await audio.read()

    # 1) ASR: speech -> text (in the user's own language)
    text = bhashini.speech_to_text(audio_bytes, src_lang=lang)

    # 2) brain: text -> grounded service match (against the live catalog)
    result = match_service(text, store.get())

    # 3) build a spoken reply in the user's language
    if result["matched"]:
        reply = f"{result['service_name_hi'] or result['service_name']} " \
                f"available hai. {len(result['required_items'])} cheezein chahiye."
    else:
        reply = "Yeh seva abhi available nahi hai."

    # 4) TTS: reply text -> speech
    reply_audio = bhashini.text_to_speech(reply, src_lang=lang)

    return {
        "transcribed_text": text,
        "match": result,
        "reply_text": reply,
        "reply_audio_wav_b64": base64.b64encode(reply_audio).decode(),
    }


# ---- serve the voice web app ---------------------------------------
# Visit  http://127.0.0.1:8000/  to open the KaryaSetu voice assistant.
_frontend = os.path.join(BASE_DIR, "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")

