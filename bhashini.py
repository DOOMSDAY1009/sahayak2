"""
Bhashini voice layer — ASR (speech->text) and TTS (text->speech).
==============================================================
Bhashini is India's national language stack: free, government-backed,
strong on Indian languages/dialects. Perfect for KaryaSetu's voice-only,
low-literacy users.

HOW BHASHINI WORKS (2 calls):
  1. ULCA "pipeline config" endpoint  -> tells you the model + callback
     URL + auth headers for the languages you want.
  2. The "compute" callback URL        -> actually runs ASR or TTS.

YOU MUST DO (one-time): register at https://bhashini.gov.in (ULCA),
create an app, and get your USER_ID + ULCA_API_KEY. Put them in env vars:
    BHASHINI_USER_ID, BHASHINI_API_KEY

Until those are set, the API still runs — voice endpoints just return a
clear "configure Bhashini" message, while the /match (text) endpoint
works fully. This keeps Phase 1 unblocked.
"""

import base64
import os
import requests

USER_ID = os.environ.get("BHASHINI_USER_ID")
API_KEY = os.environ.get("BHASHINI_API_KEY")

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
PIPELINE_ID = "64392f96daac500b55c543cd"  # Bhashini's public MeitY pipeline

is_configured = bool(USER_ID and API_KEY)


def _get_pipeline(task, src_lang, tgt_lang=None):
    """Step 1: ask ULCA which model/URL/headers to use for this task."""
    cfg = {"language": {"sourceLanguage": src_lang}}
    if tgt_lang:
        cfg["language"]["targetLanguage"] = tgt_lang
    body = {"pipelineTasks": [{"taskType": task, "config": cfg}],
            "pipelineRequestConfig": {"pipelineId": PIPELINE_ID}}
    r = requests.post(
        CONFIG_URL, json=body,
        headers={"userID": USER_ID, "ulcaApiKey": API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _compute(pipeline, task_payload):
    """Step 2: call the callback URL returned by the config step."""
    cb = pipeline["pipelineInferenceAPIEndPoint"]
    url = cb["callbackUrl"]
    key = cb["inferenceApiKey"]
    headers = {key["name"]: key["value"]}
    r = requests.post(url, json=task_payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def speech_to_text(audio_bytes, src_lang="hi"):
    """ASR: spoken audio (bytes) -> transcribed text in its own language."""
    if not is_configured:
        raise RuntimeError("Bhashini not configured — set BHASHINI_USER_ID and BHASHINI_API_KEY.")
    pipe = _get_pipeline("asr", src_lang)
    svc = pipe["pipelineResponseConfig"][0]["config"][0]["serviceId"]
    audio_b64 = base64.b64encode(audio_bytes).decode()
    payload = {
        "pipelineTasks": [{
            "taskType": "asr",
            "config": {"language": {"sourceLanguage": src_lang},
                       "serviceId": svc, "audioFormat": "wav",
                       "samplingRate": 16000},
        }],
        "inputData": {"audio": [{"audioContent": audio_b64}]},
    }
    out = _compute(pipe, payload)
    return out["pipelineResponse"][0]["output"][0]["source"]


def text_to_speech(text, src_lang="hi"):
    """TTS: text -> spoken audio (returns WAV bytes) to play back to user."""
    if not is_configured:
        raise RuntimeError("Bhashini not configured — set BHASHINI_USER_ID and BHASHINI_API_KEY.")
    pipe = _get_pipeline("tts", src_lang)
    svc = pipe["pipelineResponseConfig"][0]["config"][0]["serviceId"]
    payload = {
        "pipelineTasks": [{
            "taskType": "tts",
            "config": {"language": {"sourceLanguage": src_lang},
                       "serviceId": svc, "gender": "female"},
        }],
        "inputData": {"input": [{"source": text}]},
    }
    out = _compute(pipe, payload)
    audio_b64 = out["pipelineResponse"][0]["audio"][0]["audioContent"]
    return base64.b64decode(audio_b64)
