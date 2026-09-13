"""
KaryaSetu — NLP intent matcher
==============================================================
Turns a user's spoken complaint (in ANY Indian language, already
transcribed to text by Bhashini ASR) into a structured, GROUNDED
service match.

THE ALGORITHM (6 steps):
    1. NORMALIZE   clean the messy voice-transcribed text
    2. FAST-PATH   obvious keyword? answer without the LLM   (cost saver)
    3. LLM REASON  text + catalog -> {service, items, lang, urgency, conf}
    4. VALIDATE    is the returned service_id REAL? (anti-hallucination)
    5. ENRICH      attach the catalog's item-checklist
    6. RESOLVE     matched -> items | not matched -> log demand

Design rule: the LLM reasons, but service_catalog.json is the single
source of truth. The model can NEVER invent a service we don't offer.
"""

import json
import os
from openai import OpenAI

# ====================================================================
# MODEL SWITCH  (founder's plan: test on free Llama/Groq, swap to OpenAI
# with ZERO code changes — both speak the same API format).
#
# To switch: just set ONE environment variable before running:
#     LLM_PROVIDER=groq     -> free Llama (testing)        [default]
#     LLM_PROVIDER=openai   -> OpenAI gpt-4o-mini (prod)
# ====================================================================
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",  # Groq = OpenAI-compatible
        "api_key_env": "GROQ_API_KEY",
        "model": "llama-3.1-8b-instant",  # free, fast — llama-3.3-70b-versatile was deprecated by Groq,  
    },
    "openai": {
        "base_url": None,  # OpenAI default endpoint
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",  # cheap + smart enough for routing
    },
}

PROVIDER = os.environ.get("LLM_PROVIDER", "groq").lower()
if PROVIDER not in PROVIDERS:
    raise ValueError(f"LLM_PROVIDER must be one of {list(PROVIDERS)}, got '{PROVIDER}'")
CFG = PROVIDERS[PROVIDER]

_client = None


def get_client():
    """Lazy init: the server can boot (and serve /services, /voice config)
    without a key — the key is only needed when /match actually runs.
    Reads the right key + endpoint for whichever provider is selected."""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get(CFG["api_key_env"]),
            base_url=CFG["base_url"],
        )
    return _client


def active_model():
    return {"provider": PROVIDER, "model": CFG["model"]}


# --------------------------------------------------------------------
# Load the catalog (ground truth)
# --------------------------------------------------------------------
def load_catalog(path="service_catalog.json"):
    with open(path, encoding="utf-8") as f:
        services = json.load(f)["services"]
    # index by id for O(1) validation/enrichment in steps 4 & 5
    return {s["id"]: s for s in services}


# --------------------------------------------------------------------
# STEP 1 — NORMALIZE
# Voice transcription is noisy: extra spaces, casing, stray punctuation.
# --------------------------------------------------------------------
def normalize(text):
    return " ".join(text.strip().split())


# --------------------------------------------------------------------
# STEP 2 — FAST-PATH (optional, Phase-2 cost optimization)
# If an unambiguous keyword is present we can skip the LLM entirely.
# Conservative on purpose: only fires when EXACTLY ONE service matches,
# so ambiguous requests still go to the smart path.
# --------------------------------------------------------------------
def fast_path(text, catalog):
    low = text.lower()
    hits = [
        sid for sid, s in catalog.items()
        if any(k.lower() in low for k in s.get("keywords", []))
    ]
    if len(hits) == 1:
        return hits[0]
    return None  # 0 hits (need LLM) or >1 hit (ambiguous -> need LLM)


# --------------------------------------------------------------------
# STEP 3 — LLM REASON
# We hand the model a COMPACT view of the catalog and force structured
# JSON output. The model understands the native language directly, so
# no separate translation step is needed.
# --------------------------------------------------------------------
def build_catalog_for_prompt(catalog):
    # id + description + standard items, so the model can translate the
    # items into the user's language while staying grounded to the catalog.
    return [{"id": s["id"], "what_it_is": s["description"],
             "items": s.get("default_items", [])}
            for s in catalog.values()]


# The exact JSON shape we want back. Described in the prompt (not as a
# strict API schema) so it works IDENTICALLY on Groq/Llama AND OpenAI.
JSON_SHAPE = """{
  "service_id": "<an id from the catalog, or 'none'>",
  "service_name_local": "<the service name IN THE USER'S OWN LANGUAGE & SCRIPT>",
  "problem_summary": "<one short line IN THE USER'S OWN LANGUAGE & SCRIPT>",
  "language_detected": "<language code, e.g. hi, ta, en>",
  "matched": <true or false>,
  "confidence": <number between 0 and 1>,
  "required_items": ["<item IN THE USER'S OWN LANGUAGE & SCRIPT>", "..."],
  "urgency": "<low | normal | high | emergency>"
}"""


def llm_reason(text, catalog, reply_language=None):
    # The output language is whatever the app/user selected. If none given,
    # fall back to matching the user's input language.
    if reply_language:
        lang_rule = (
            f"VERY IMPORTANT: write service_name_local, problem_summary and EVERY "
            f"required_items entry in {reply_language} ONLY, regardless of what "
            f"language the user spoke in. "
        )
    else:
        lang_rule = (
            "VERY IMPORTANT: write service_name_local, problem_summary and EVERY "
            "required_items entry in the SAME language and script as the user's "
            "request (e.g. Hindi request -> Hindi output, Tamil -> Tamil). "
        )
    system = (
        "You are KaryaSetu's request router for an Indian services app. "
        "The user speaks in their own language about a problem or need. "
        "Map it to EXACTLY ONE service from the provided catalog by its 'id'. "
        "Infer the real need: 'tap not working' -> plumber; "
        "'I need to harvest my crop' -> harvester_rental. "
        "List the practical items/sub-services needed to fulfil it; include the "
        "service's standard 'items' from the catalog. "
        + lang_rule +
        "Only service_id and language_detected stay in English. "
        "If NOTHING in the catalog fits, set service_id='none' and matched=false. "
        "Never invent an id that is not in the catalog. "
        "Reply with ONLY a JSON object in exactly this shape:\n" + JSON_SHAPE
    )
    user = (
        f"CATALOG:\n{json.dumps(build_catalog_for_prompt(catalog), ensure_ascii=False)}\n\n"
        f"USER REQUEST (any language):\n{text}"
    )
    resp = get_client().chat.completions.create(
        model=CFG["model"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},  # portable: Groq + OpenAI both support
        temperature=0,
        # (reply_language baked into the system prompt above)
    )
    return json.loads(resp.choices[0].message.content)


# --------------------------------------------------------------------
# STEPS 4-6 — VALIDATE, ENRICH, RESOLVE
# --------------------------------------------------------------------
def finalize(result, catalog, raw_text):
    sid = result.get("service_id")

    # STEP 4 — VALIDATE: reject anything not actually in our catalog.
    if not result.get("matched") or sid not in catalog:
        return {
            "matched": False,
            "raw_text": raw_text,
            "problem_summary": result.get("problem_summary", ""),
            "language_detected": result.get("language_detected", "unknown"),
            "message": "We don't offer this service yet — logged as demand.",
        }

    service = catalog[sid]

    # STEP 5 — ENRICH: use the model's localized items (already in the user's
    # language). Fall back to the English catalog list if the model gave none.
    items = result.get("required_items") or service.get("default_items", [])

    # STEP 6 — RESOLVE
    return {
        "matched": True,
        "raw_text": raw_text,
        "service_id": sid,
        "service_name": service["name_en"],            # English (for the app team)
        "service_name_local": result.get("service_name_local") or service["name_en"],
        "service_name_hi": service.get("name_hi", ""),
        "problem_summary": result.get("problem_summary", ""),  # in user's language
        "language_detected": result.get("language_detected", "unknown"),
        "confidence": result.get("confidence", 0),
        "urgency": result.get("urgency", "normal"),
        "required_items": items,                        # in user's language
    }


def log_unmatched(result):
    """Phase-1 demand discovery: unmatched requests = your roadmap.

    Serverless hosts (e.g. Vercel) have a read-only filesystem except /tmp,
    and that /tmp is ephemeral. Write there when running on Vercel, and never
    let a logging failure break the actual match response."""
    path = "/tmp/unmatched_requests.log" if os.environ.get("VERCEL") \
        else "unmatched_requests.log"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------
# PUBLIC ENTRY POINT — the whole funnel
# --------------------------------------------------------------------
def match_service(user_text, catalog, use_fast_path=False, reply_language=None):
    text = normalize(user_text)                       # 1

    if use_fast_path:                                 # 2 (optional)
        sid = fast_path(text, catalog)
        if sid:
            return finalize(
                {"matched": True, "service_id": sid, "confidence": 0.6,
                 "required_items": [], "problem_summary": text,
                 "language_detected": "n/a (keyword)", "urgency": "normal"},
                catalog, text,
            )

    raw = llm_reason(text, catalog, reply_language)   # 3
    final = finalize(raw, catalog, text)              # 4-6
    if not final["matched"]:
        log_unmatched(final)
    return final


# --------------------------------------------------------------------
# DEMO — run:  python matcher.py
# --------------------------------------------------------------------
if __name__ == "__main__":
    catalog = load_catalog()

    samples = [
        "मेरा नल खराब हो गया है, पानी टपक रहा है",   # Hindi: tap broken, leaking
        "I need to harvest my crops",                  # English: -> harvester
        "ghar me bijli nahi aa rahi, fan band hai",    # Romanized Hindi: no power
        "எனக்கு என் வீட்டை சுத்தம் செய்ய வேண்டும்",     # Tamil: clean my house
        "naya ghar shift karna hai agle hafte",        # moving home
        "mujhe ek tractor chahiye khet jotne ke liye", # tractor to plough
        "I want to learn guitar",                       # NOT in catalog -> unmatched
    ]

    for s in samples:
        r = match_service(s, catalog)
        print("\n" + "=" * 60)
        print("USER:", s)
        if r["matched"]:
            print(f"  -> {r['service_name']} ({r['service_id']})  "
                  f"[{r['language_detected']}, {r['urgency']}, "
                  f"conf={r['confidence']}]")
            print("  items:", ", ".join(r["required_items"]))
        else:
            print("  -> NO MATCH:", r["message"])
