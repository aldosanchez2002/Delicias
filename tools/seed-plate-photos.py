#!/usr/bin/env python3
"""Copy the studio plate photos into Firebase Storage and point the labels at them.

The photos currently ship from the repo, which means adding one needs a commit.
Moving them to Storage lets the admin tools upload directly. Each label document
already carries a url field that index.html feeds straight to an <img>, so a
Storage URL drops in with no code change.

The repo copies are deliberately left in place: they cost nothing, they keep git
history intact, and they make --rollback a one-liner if Storage ever misbehaves.

Usage:
    python3 tools/seed-plate-photos.py              # dry run, changes nothing
    python3 tools/seed-plate-photos.py --apply      # upload, verify, then repoint
    python3 tools/seed-plate-photos.py --rollback   # point labels back at the repo
"""
import argparse, hashlib, json, os, sys, urllib.error, urllib.parse, urllib.request

PROJECT = "delicias-4b2b1"
BUCKET = "delicias-4b2b1.firebasestorage.app"
API_KEY = "AIzaSyC88JpbLzapZUcV-Y17Y9RUvwYuwSc2Dmw"
FS = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
ST = f"https://firebasestorage.googleapis.com/v0/b/{BUCKET}/o"
PREFIX = "plate-photos"
LOCAL = "PlatePicturesStudio"


def http(url, method="GET", body=None, ctype="application/json"):
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw and ctype == "application/json" else raw


def public_url(name):
    return f"{ST}/{urllib.parse.quote(f'{PREFIX}/{name}', safe='')}?alt=media"


def preflight():
    """Fail loudly and specifically rather than half-migrating."""
    try:
        http(ST)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sys.exit("Storage bucket does not exist yet. Enable Storage in the Firebase "
                     "console (Storage -> Get started), then re-run.")
        if e.code == 403:
            # Expected: the rules grant read on plate-photos/{file}, not on the bucket
            # root, so listing is denied while the uploads below still work.
            print("note: bucket listing is denied by the rules (expected); continuing")
            return
        raise


def load_labels():
    docs = http(f"{FS}/platePhotos?key={API_KEY}&pageSize=300").get("documents", [])
    return {d["name"].split("/")[-1]: d["fields"] for d in docs}


def set_url_field(doc_id, fields, value):
    fields = dict(fields)
    fields["url"] = {"stringValue": value}
    http(f"{FS}/platePhotos/{doc_id}?key={API_KEY}", "PATCH",
         json.dumps({"fields": fields}).encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform the migration")
    ap.add_argument("--rollback", action="store_true", help="repoint labels at the repo")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    labels = load_labels()

    if args.rollback:
        # Documents are keyed by auto-id now, so the repo filename comes from
        # storagePath rather than the document id.
        n = 0
        for doc_id, fields in labels.items():
            url = fields.get("url", {}).get("stringValue", "")
            name = os.path.basename(fields.get("storagePath", {}).get("stringValue", ""))
            if url.startswith("http") and name and os.path.exists(os.path.join(LOCAL, name)):
                set_url_field(doc_id, fields, f"{LOCAL}/{name}")
                n += 1
        print(f"pointed {n} labels back at {LOCAL}/")
        return

    preflight()
    files = sorted((f for f in os.listdir(LOCAL) if f.lower().endswith(".jpg")),
                   key=lambda f: int(f.split(".")[0]))
    print(f"{len(files)} photos in {LOCAL}/, {len(labels)} labels in Firestore")

    known = {os.path.basename(v.get("storagePath", {}).get("stringValue", "")) for v in labels.values()}
    orphans = [f for f in files if f not in known]
    if orphans:
        print(f"  note: no label for {orphans} (they will still be uploaded)")

    if not args.apply:
        for f in files[:3]:
            print(f"  would upload {LOCAL}/{f} -> {PREFIX}/{f}")
        print(f"  ... {len(files)} total\n  then repoint each label to its Storage URL")
        print("\ndry run only. re-run with --apply to perform it.")
        return

    # 1. upload everything before touching Firestore, so a failure leaves the site intact
    uploaded = []
    for f in files:
        data = open(os.path.join(LOCAL, f), "rb").read()
        url = f"{ST}?uploadType=media&name={urllib.parse.quote(f'{PREFIX}/{f}', safe='')}"
        try:
            http(url, "POST", data, "image/jpeg")
        except urllib.error.HTTPError as e:
            sys.exit(f"upload of {f} failed with HTTP {e.code}: {e.read()[:200].decode('utf8','ignore')}\n"
                     "Check the Storage rules allow writes to plate-photos/.")
        uploaded.append(f)
        print(f"  uploaded {f} ({len(data)/1024:.0f} KB)")

    # 2. verify each object is publicly readable and byte-identical before repointing
    for f in uploaded:
        got = http(public_url(f), ctype="image/jpeg")
        local = open(os.path.join(LOCAL, f), "rb").read()
        if hashlib.sha256(got).hexdigest() != hashlib.sha256(local).hexdigest():
            sys.exit(f"{f} read back from Storage does not match the local file; stopping "
                     "before any label is repointed.")
    print(f"verified {len(uploaded)} objects are public and byte-identical")

    # 3. only now repoint the labels
    by_name = {os.path.basename(v.get("storagePath", {}).get("stringValue", "")): k
               for k, v in labels.items()}
    n = 0
    for f in uploaded:
        if f in by_name:
            set_url_field(by_name[f], labels[by_name[f]], public_url(f))
            n += 1
    print(f"repointed {n} labels at Storage")
    print("\nrepo copies were left in place; --rollback reverts the labels if needed.")


if __name__ == "__main__":
    main()
