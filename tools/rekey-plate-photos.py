#!/usr/bin/env python3
"""Re-key plate photo labels from filenames to Firestore auto-ids.

Labels used to be keyed by filename ("1.jpg"), which made the filename an
identity: renaming or renumbering a photo silently detached its label, and the
labeling tool had to guess filenames by probing to find photos at all.

Now that the images live in Storage, the document id can be the identity and the
Storage object name becomes irrelevant. That means this migration never touches a
single image: it only rewrites Firestore.

  file        -> url          (it is a URL, not a path)
  <new>          storagePath  (so a photo can later be replaced or removed)
  <new>          createdAt    (display ordering, replacing the old numbering)

Usage:
    python3 tools/rekey-plate-photos.py            # dry run
    python3 tools/rekey-plate-photos.py --apply
"""
import argparse, json, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

PROJECT = "delicias-4b2b1"
API_KEY = "AIzaSyC88JpbLzapZUcV-Y17Y9RUvwYuwSc2Dmw"
FS = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


def http(url, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def storage_path_from_url(url):
    """plate-photos/1.jpg out of .../o/plate-photos%2F1.jpg?alt=media"""
    if "/o/" not in url:
        return ""
    tail = url.split("/o/", 1)[1].split("?", 1)[0]
    return urllib.parse.unquote(tail)


def sort_key(doc_id):
    """Preserve today's visible order: 1.jpg, 2.jpg, ... then anything else."""
    stem = doc_id.split(".")[0]
    return (0, int(stem)) if stem.isdigit() else (1, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    docs = http(f"{FS}/platePhotos?key={API_KEY}&pageSize=300").get("documents", [])
    old = [d for d in docs if not d["fields"].get("url")]  # already-migrated docs have url
    if not old:
        print("nothing to do: every label already uses an auto-id schema")
        return

    old.sort(key=lambda d: sort_key(d["name"].split("/")[-1]))
    print(f"{len(old)} labels to re-key (of {len(docs)} total)")

    # Synthesised so the existing order survives; real uploads will use serverTimestamp
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    if not args.apply:
        for d in old[:3]:
            did = d["name"].split("/")[-1]
            url = d["fields"]["file"]["stringValue"]
            print(f"  {did:8s} -> auto-id, storagePath={storage_path_from_url(url)}")
        print(f"  ... {len(old)} total\n\ndry run only. re-run with --apply.")
        return

    created = []
    for i, d in enumerate(old):
        did = d["name"].split("/")[-1]
        f = dict(d["fields"])
        url = f.pop("file")["stringValue"]
        f["url"] = {"stringValue": url}
        f["storagePath"] = {"stringValue": storage_path_from_url(url)}
        f["createdAt"] = {"timestampValue": (base + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")}
        try:
            new = http(f"{FS}/platePhotos?key={API_KEY}", "POST", {"fields": f})
        except urllib.error.HTTPError as e:
            sys.exit(f"failed creating replacement for {did}: HTTP {e.code} "
                     f"{e.read()[:200].decode('utf8','ignore')}\nNo old document was deleted.")
        created.append((did, new["name"].split("/")[-1]))
        print(f"  {did:8s} -> {created[-1][1]}")

    # Only delete the originals once every replacement exists
    for did, _ in created:
        http(f"{FS}/platePhotos/{did}?key={API_KEY}", "DELETE")
    print(f"\nre-keyed {len(created)} labels and removed the filename-keyed originals")
    print("images in Storage were not touched")


if __name__ == "__main__":
    main()
