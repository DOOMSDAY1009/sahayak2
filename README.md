# KaryaSetu — NLP Intent Matcher (Phase 1)

Turns a user's spoken complaint (any Indian language) into a **grounded**
service match. Voice is handled by Bhashini (ASR/TTS); this repo is the
**brain** in the middle — testable with plain text first.

## The pipeline (voice-only product)
```
🎤 speak → [Bhashini ASR] → text → [THIS CODE] → result → [Bhashini TTS] → 🔊 speak back
```

## The algorithm (`matcher.py`)
```
1. NORMALIZE   clean messy voice text
2. FAST-PATH   obvious keyword? skip the LLM        (Phase-2 cost saver)
3. LLM REASON  text + catalog → structured JSON
4. VALIDATE    is the service_id REAL? (anti-hallucination)  ← the key step
5. ENRICH      attach catalog's item checklist
6. RESOLVE     matched → items | unmatched → log as demand
```
**Golden rule:** the LLM reasons, but `service_catalog.json` is the only
source of truth. The model can never offer a service you don't have.

## Run it
```bash
pip install openai
export OPENAI_API_KEY=sk-...      # Windows PowerShell: $env:OPENAI_API_KEY="sk-..."
python matcher.py
```

## Add a new service
Edit `service_catalog.json` — add one entry. **No code change.**
Unmatched user requests are logged to `unmatched_requests.log` = your
roadmap of services to add next.

## Cost plan (founder's "stabilize then optimize")
- **Now:** `gpt-4o-mini` + free Bhashini for voice = tiny bills.
- **Later:** turn on `use_fast_path`, cache common requests, shrink the
  prompt, or swap to an open model.
```
```
