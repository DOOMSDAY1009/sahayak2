"""
Live catalog store — keeps the engine's service list IN SYNC with the app.
==============================================================
The KaryaSetu app OWNS the services. This engine just mirrors them.
Whenever the app's services change (a new one added, one removed), the app
pushes the current list here via  POST /catalog/sync  and the engine
immediately starts matching against it — no restart, no code change.

The app's service objects can be minimal. We accept flexible field names
and fill sensible defaults, so the engine works whatever shape the app uses:
    required : id (or service_id), name (or name_en)
    optional : description, name_hi, keywords, default_items (or items)
"""

import json


def normalize_service(raw):
    """Map an app's service object into the engine's internal shape."""
    sid = raw.get("id") or raw.get("service_id")
    name = raw.get("name_en") or raw.get("name") or sid
    return {
        "id": sid,
        "name_en": name,
        "name_hi": raw.get("name_hi", ""),
        # description drives the AI matching — fall back to the name if absent
        "description": raw.get("description") or name or "",
        "keywords": raw.get("keywords", []),
        "default_items": raw.get("default_items") or raw.get("items") or [],
    }


class CatalogStore:
    """Holds the current catalog in memory as {id: service}."""

    def __init__(self):
        self._by_id = {}

    def set_services(self, services):
        """Replace the whole catalog with the app's current list."""
        cat = {}
        for raw in services:
            s = normalize_service(raw)
            if s["id"]:                       # skip entries with no id
                cat[s["id"]] = s
        self._by_id = cat
        return len(cat)

    def get(self):
        """The live catalog the matcher reads on every request."""
        return self._by_id

    def as_list(self):
        return [{"id": s["id"], "name": s["name_en"], "description": s["description"]}
                for s in self._by_id.values()]

    def load_file(self, path):
        """Seed the catalog from the bundled JSON at startup."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return self.set_services(data["services"])


# single shared instance used by the API
store = CatalogStore()
