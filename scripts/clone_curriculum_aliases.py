"""One-shot: clone existing curriculum .txt files under their notes pretty-title aliases.

After the .txt-suffix migration, ``notes_crew/data/reading_materials.yaml``
references books under "pretty title" filenames (e.g. ``Bruce Block - The
Visual Story.txt``) while ``quiz_crew/data/reading_materials.yaml`` keeps
the original n8n-era PDF basenames (e.g.
``Bruce-Block-The-Visual-Story-Creating-...-2021.txt``). The bucket only
has the quiz variants — the notes pretty titles 404, so the runtime
falls back to "(no full-text content available)".

Fix: copy each existing object's bytes to the missing alias name,
server-side (no round-trip through this machine's disk).

Idempotent: if the target already exists with byte-identical content,
skip it. Run as many times as you want.

Env (read from .env): ``SUPABASE_URL``, ``SUPABASE_SERVICE_KEY``.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BUCKET = "curriculum"

# (existing-in-bucket → notes pretty-title alias to create).
# Both names refer to the same book; we just want both spellings to
# resolve so notes and quiz crews fetch the same bytes.
ALIASES: list[tuple[str, str]] = [
    (
        "Ways of Seeing .txt",
        "Ways of Seeing.txt",
    ),
    (
        "Film Art_ An Introduction 10th Edition ( PDFDrive ).txt",
        "Film Art_ An Introduction 10th Edition (PDFDrive).txt",
    ),
    (
        "The Five C's of Cinematography_ Motion Picture Filming Techniques(1).txt",
        "The Five C's of Cinematography_ Motion Picture Filming Techniques.txt",
    ),
    (
        "Screenplay; The Foundations of Screenwriting, revised & updated - Syd Field.txt",
        "Screenplay; The Foundations of Screenwriting - Syd Field.txt",
    ),
    (
        "Film editing karel reiz.txt",
        "Film editing - Karel Reisz.txt",
    ),
    (
        "Bruce-Block-The-Visual-Story-Creating-the-Visual-Structure-of-Film-TV-And-Digital-Media-2021.txt",
        "Bruce Block - The Visual Story.txt",
    ),
    (
        "On Writing_ A Memoir of the Craft - Stephen King.txt",
        "On Writing - Stephen King.txt",
    ),
    (
        "The Stories of Anton Chekhov (Anton Chekhov).txt",
        "The Stories of Anton Chekhov.txt",
    ),
    (
        "toaz.info-save-the-cat-by-blake-snyder-pr_8defda23000f86ee7b077787303fa715.txt",
        "Save the Cat - Blake Snyder.txt",
    ),
    (
        "Film Directing Shot by shot .txt",
        "Film Directing Shot by Shot.txt",
    ),
    (
        "ilide.info-becoming-an-actorx27s-director-directing-actors-for-film-and-television-regg-pr_2c3d1d2c691c8c718bed0ca1c547c1e1.txt",
        "Becoming an Actor's Director - Regge Life.txt",
    ),
    (
        "Directing Actors_ Creating Memorable Performances for Film & Television.txt",
        "Directing Actors - Judith Weston.txt",
    ),
    (
        "Dialogue_-_Robert_McKee.txt",
        "Dialogue - Robert McKee.txt",
    ),
]


def _public_url(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(path, safe='/')}"


def _admin_url(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{urllib.parse.quote(path, safe='/')}"


def fetch_bytes(client: httpx.Client, path: str) -> bytes | None:
    r = client.get(_public_url(path), timeout=60)
    if r.status_code == 200:
        return r.content
    if r.status_code in (400, 404):
        return None
    r.raise_for_status()
    return None


def upload(client: httpx.Client, path: str, body: bytes) -> None:
    headers = {
        "Authorization": f"Bearer {SERVICE_KEY}",
        "apikey": SERVICE_KEY,
        "Content-Type": "text/plain; charset=utf-8",
        "x-upsert": "true",
        "cache-control": "max-age=3600",
    }
    r = client.post(_admin_url(path), headers=headers, content=body, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload {path} failed: {r.status_code} {r.text[:300]}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cloned = 0
    skipped_identical = 0
    failed: list[tuple[str, str, str]] = []

    with httpx.Client() as client:
        for source, target in ALIASES:
            print(f"\n{source}\n  → {target}")
            src_bytes = fetch_bytes(client, source)
            if src_bytes is None:
                print(f"  ! source missing in bucket")
                failed.append((source, target, "source missing"))
                continue

            existing = fetch_bytes(client, target)
            if existing == src_bytes:
                skipped_identical += 1
                print(f"  = target exists & matches ({len(src_bytes)} bytes)")
                continue

            try:
                upload(client, target, src_bytes)
            except Exception as exc:
                print(f"  ! upload failed: {exc}")
                failed.append((source, target, str(exc)[:200]))
                continue

            cloned += 1
            print(f"  ✓ cloned ({len(src_bytes)} bytes)")

    print("\n=== Summary ===")
    print(f"  Aliases cloned:  {cloned}")
    print(f"  Already in sync: {skipped_identical}")
    print(f"  Failures:        {len(failed)}")
    for src, tgt, why in failed:
        print(f"    - {src!r} → {tgt!r}: {why}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
