# KaryaSetu — AI/NLP Engine: Integration Guide for the App Team

This is the **contract** between the AI engine and the main KaryaSetu app.
The app does NOT need to know how the AI works — it just sends a request
and gets a clean JSON answer. Works from any language (React, Flutter,
Node, etc.) because it's a standard HTTP API.

---

## 1. What this engine does
Takes a user's request in ANY Indian language (text) and returns the
matched KaryaSetu service + the items needed to fulfil it.

## 2. Where it runs
During development it runs locally at:  `http://127.0.0.1:8000`
In production it will run on a server (a hosted URL the app will call instead).

---

## 3. The main endpoint the app should call

### `POST /match`
**Send this (JSON body):**
```json
{
  "text": "mera nal kharab hai",
  "use_fast_path": false
}
```

**You get back (matched example):**
```json
{
  "matched": true,
  "service_id": "plumber",
  "service_name": "Plumber",
  "service_name_hi": "प्लंबर",
  "problem_summary": "tap is broken / leaking",
  "language_detected": "hi",
  "confidence": 0.95,
  "urgency": "normal",
  "required_items": ["plumber visit charge", "spare parts (washer / tap / pipe)"]
}
```

**You get back (no service available):**
```json
{
  "matched": false,
  "message": "We don't offer this service yet — logged as demand.",
  "problem_summary": "...",
  "language_detected": "hi"
}
```

**How the app should use it:**
- If `matched: true` → show `service_name` + the `required_items` list, then
  proceed to find/book a worker for `service_id`.
- If `matched: false` → show a polite "service coming soon" message.

---

## 4. Keeping the engine in sync with the app  ⭐ IMPORTANT

The app OWNS the services. The engine just mirrors them. Whenever services
change in the app (new one added, edited, or removed), the app must push the
**full current list** to the engine. Then Sahayak matches against it
immediately — no restart, no code change.

### `POST /catalog/sync`
Call this on app startup AND every time the service list changes.
```json
{
  "services": [
    { "id": "plumber",  "name": "Plumber",   "description": "Fixes taps, pipes, leaks, drainage" },
    { "id": "tutor",    "name": "Home Tutor","description": "Private tuition at home for children" },
    { "id": "cook",     "name": "Cook",      "description": "Cooking and meal prep at home" }
  ]
}
```
**Field rules (flexible):**
- **required:** `id`, `name` (description is strongly recommended — the AI
  matches on it; without it, accuracy drops).
- **optional:** `name_hi`, `keywords`, `default_items` (a.k.a. `items`).

Response: `{ "synced": true, "services_loaded": 3 }`

> Easiest pattern: in your app's "add/edit/delete service" code, after saving
> to your DB, send the whole updated services array to `/catalog/sync`.
> A brand-new service becomes matchable instantly; a removed one immediately
> starts returning `matched:false` ("service not available yet").

## 5. Helper endpoints

### `GET /services`
Returns the services the engine currently knows about (the live catalog).
Useful to confirm a sync worked, or to show a menu/icons in the app.

### `GET /`
Health check. Returns `{ "status": "ok", ... }`. Use to confirm the
engine is up.

### `POST /voice/match`  (voice — activates once Bhashini keys are set)
Send an audio file (form-data: `audio` = WAV file, `lang` = "hi"/"ta"/etc.).
Returns the transcribed text, the match, and a spoken-reply audio clip.

---

## 5. Example call from the app side

**JavaScript (React / React Native / Node):**
```js
const res = await fetch("http://127.0.0.1:8000/match", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ text: userMessage, use_fast_path: false }),
});
const data = await res.json();
if (data.matched) {
  // show data.service_name and data.required_items
} else {
  // show "service coming soon"
}
```

**Flutter (Dart):**
```dart
final res = await http.post(
  Uri.parse("http://127.0.0.1:8000/match"),
  headers: {"Content-Type": "application/json"},
  body: jsonEncode({"text": userMessage, "use_fast_path": false}),
);
final data = jsonDecode(res.body);
```

That's the whole integration. The app sends text, gets structured JSON,
shows it to the user. Everything else is handled inside the engine.
