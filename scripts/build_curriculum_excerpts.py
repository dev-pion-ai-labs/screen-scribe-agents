"""Offline pipeline: build per-(book, subtopic) excerpt files for the curriculum bucket.

For each subtopic→book mapping in the three YAMLs, we want the runtime to fetch
a small focused excerpt instead of the whole book. This script produces those
excerpts using a hybrid retrieval pass (BM25 → top-20 → embedding rerank → top-5)
and uploads them to Supabase Storage alongside the existing whole-book .txt files.

Embeddings are cached as JSON under ``_embeddings/<book-slug>.json`` in the same
bucket so re-runs only re-embed books whose source text actually changed
(detected via SHA-256 of the .txt body).

Install: ``pip install -e ".[pipeline]"`` (adds ``rank-bm25``).
Env: ``SUPABASE_URL``, ``SUPABASE_SERVICE_KEY``, ``GEMINI_API_KEY`` (read from .env).

Usage:
    python scripts/build_curriculum_excerpts.py                   # full backfill
    python scripts/build_curriculum_excerpts.py --book "Foo.txt"  # one book
    python scripts/build_curriculum_excerpts.py --subtopic "x"    # one subtopic
    python scripts/build_curriculum_excerpts.py --dry-run         # don't upload
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

# Windows console defaults to cp1252; the script's logs and the chunk
# separator '[…]' contain non-ASCII glyphs.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse the slug helper so pipeline filenames match runtime fetch logic.
from app.services.document_store import _excerpt_filename, _subtopic_slug  # noqa: E402

load_dotenv(ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
BUCKET = "curriculum"
EMBEDDING_PREFIX = "_embeddings"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768  # gemini-embedding-001 supports configurable output dim

# Chunking: paragraph-packed windows. ~3200 chars ≈ ~800 tokens.
CHUNK_TARGET_CHARS = 3200
CHUNK_OVERLAP_CHARS = 300

# Retrieval: hybrid BM25 → top-20 → embedding rerank → top-5.
BM25_TOP = 20
RERANK_TOP_K = 5

# Gemini batch embed cap — keep well below provider limit.
EMBED_BATCH_SIZE = 50

# Soft separator between concatenated chunks in the excerpt body.
CHUNK_SEPARATOR = "\n\n[…]\n\n"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    idx: int
    text: str
    embedding: list[float]


@dataclass
class BookCorpus:
    filename: str
    source_hash: str
    chunks: list[Chunk]


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_subtopic_book_pairs() -> dict[str, set[str]]:
    """Return {book_filename: {subtopic, ...}} aggregated across all three YAMLs.

    Skips URLs and activity-flag values (anything not ending in .txt).
    """
    pairs: dict[str, set[str]] = {}

    def add(subtopic: str, value: str) -> None:
        if not value or not value.endswith(".txt"):
            return
        pairs.setdefault(value, set()).add(subtopic)

    for yaml_path in (
        ROOT / "app/crews/notes_crew/data/reading_materials.yaml",
        ROOT / "app/crews/quiz_crew/data/reading_materials.yaml",
    ):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for subtopic, vals in data.items():
            for v in vals:
                add(subtopic, v)

    eval_data = yaml.safe_load(
        (ROOT / "app/crews/assignment_crew/data/evaluation_documents.yaml").read_text(
            encoding="utf-8"
        )
    )
    for subtopic, v in eval_data.items():
        add(subtopic, v)

    return pairs


# ---------------------------------------------------------------------------
# Bucket I/O
# ---------------------------------------------------------------------------


def _public_url(path: str) -> str:
    import urllib.parse

    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(path, safe='/')}"


def _admin_url(path: str) -> str:
    import urllib.parse

    return f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{urllib.parse.quote(path, safe='/')}"


# Supabase Storage returns 400 (with `{"error":"Object not found"}`) for missing
# public objects, plus 404 in some configurations. Treat both as "not present"
# and let real auth/permission errors (401/403) bubble up.
_MISSING_STATUSES = (400, 404)


def fetch_text(path: str, client: httpx.Client) -> str | None:
    r = client.get(_public_url(path), timeout=60)
    if r.status_code == 200:
        return r.text
    if r.status_code in _MISSING_STATUSES:
        return None
    r.raise_for_status()
    return None


def fetch_json(path: str, client: httpx.Client) -> dict | None:
    r = client.get(_public_url(path), timeout=60)
    if r.status_code == 200:
        return r.json()
    if r.status_code in _MISSING_STATUSES:
        return None
    r.raise_for_status()
    return None


def upload(
    path: str,
    body: bytes,
    content_type: str,
    client: httpx.Client,
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"  [dry-run] would upload {path} ({len(body)} bytes)")
        return
    headers = {
        "Authorization": f"Bearer {SERVICE_KEY}",
        "apikey": SERVICE_KEY,
        "Content-Type": content_type,
        "x-upsert": "true",
        "cache-control": "max-age=3600",
    }
    r = client.post(_admin_url(path), headers=headers, content=body, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload {path} failed: {r.status_code} {r.text[:300]}")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str, *, target_chars: int = CHUNK_TARGET_CHARS, overlap_chars: int = CHUNK_OVERLAP_CHARS
) -> list[str]:
    """Pack paragraphs into ~target_chars windows, overlapping by ~overlap_chars.

    Preserves paragraph boundaries so the model gets coherent passages.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in paragraphs:
        plen = len(p) + 2
        if cur and cur_len + plen > target_chars:
            chunks.append("\n\n".join(cur))
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(cur):
                if tail_len + len(prev) + 2 > overlap_chars and tail:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 2
            cur = tail
            cur_len = tail_len
        cur.append(p)
        cur_len += plen

    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


# ---------------------------------------------------------------------------
# Embeddings (Gemini text-embedding-004 via google.genai)
# ---------------------------------------------------------------------------


def _embed_client():
    from google import genai

    return genai.Client(api_key=GEMINI_API_KEY)


def embed_batch(client, texts: list[str]) -> list[list[float]]:
    """Return one ``EMBEDDING_DIM``-dim embedding per input text.

    Retries with exponential backoff on transient 429 RESOURCE_EXHAUSTED
    responses — Gemini enforces per-minute request and per-minute token
    quotas, so a long backfill regularly hits them.
    """
    from google.genai import types

    config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM)
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        delay = 30.0
        attempts = 0
        while True:
            try:
                resp = client.models.embed_content(
                    model=EMBEDDING_MODEL, contents=batch, config=config
                )
                break
            except Exception as exc:
                msg = str(exc)
                rate_limited = "429" in msg or "RESOURCE_EXHAUSTED" in msg
                if not rate_limited or attempts >= 5:
                    raise
                attempts += 1
                print(
                    f"    rate-limited, sleeping {delay:.0f}s "
                    f"(attempt {attempts}/5)"
                )
                time.sleep(delay)
                delay = min(delay * 2, 240.0)
        out.extend([list(e.values) for e in resp.embeddings])
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return (dot / (na * nb)) if (na and nb) else 0.0


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


def bm25_top(corpus_chunks: list[str], query: str, top_n: int) -> list[int]:
    from rank_bm25 import BM25Okapi

    tokenize = lambda s: re.findall(r"[A-Za-z0-9]+", s.lower())
    tokenized_corpus = [tokenize(c) for c in corpus_chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_n]


# ---------------------------------------------------------------------------
# Per-book pipeline
# ---------------------------------------------------------------------------


def book_slug_basename(book_filename: str) -> str:
    base = book_filename[:-4] if book_filename.lower().endswith(".txt") else book_filename
    return _subtopic_slug(base)


def load_or_build_corpus(
    book_filename: str,
    *,
    http: httpx.Client,
    embed_client,
    dry_run: bool,
) -> BookCorpus | None:
    """Fetch the book .txt, return a corpus with chunks + embeddings.

    Reuses the cached _embeddings/<slug>.json when its source_hash matches.
    """
    raw = fetch_text(book_filename, http)
    if raw is None:
        print(f"  ! skip {book_filename}: not found in bucket")
        return None
    if not raw.strip():
        print(f"  ! skip {book_filename}: empty body")
        return None

    source_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    cache_path = f"{EMBEDDING_PREFIX}/{book_slug_basename(book_filename)}.json"

    cached = fetch_json(cache_path, http)
    if cached and cached.get("source_hash") == source_hash:
        chunks = [
            Chunk(idx=c["idx"], text=c["text"], embedding=c["embedding"])
            for c in cached["chunks"]
        ]
        print(f"  ✓ embeddings cache HIT  {cache_path}  ({len(chunks)} chunks)")
        return BookCorpus(
            filename=book_filename, source_hash=source_hash, chunks=chunks
        )

    chunk_texts = chunk_text(raw)
    if not chunk_texts:
        print(f"  ! skip {book_filename}: no chunks after splitting")
        return None

    print(f"  → embedding {len(chunk_texts)} chunks for {book_filename}")
    started = time.perf_counter()
    embeddings = embed_batch(embed_client, chunk_texts)
    print(f"    embed took {time.perf_counter() - started:.1f}s")

    chunks = [
        Chunk(idx=i, text=t, embedding=e)
        for i, (t, e) in enumerate(zip(chunk_texts, embeddings))
    ]
    payload = json.dumps(
        {
            "source_hash": source_hash,
            "model": EMBEDDING_MODEL,
            "chunks": [
                {"idx": c.idx, "text": c.text, "embedding": c.embedding} for c in chunks
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    upload(cache_path, payload, "application/json", http, dry_run=dry_run)
    print(f"  ✓ uploaded embeddings cache {cache_path} ({len(payload)} bytes)")
    return BookCorpus(filename=book_filename, source_hash=source_hash, chunks=chunks)


# ---------------------------------------------------------------------------
# Excerpt build
# ---------------------------------------------------------------------------


def build_excerpt_body(
    corpus: BookCorpus, subtopic: str, *, embed_client
) -> tuple[str, list[int]]:
    """Hybrid retrieval: BM25 top-20 → embed rerank → top-K. Returns (body, idxs)."""
    chunk_texts = [c.text for c in corpus.chunks]
    if len(chunk_texts) <= RERANK_TOP_K:
        # Tiny book — just use everything in source order.
        idxs = list(range(len(chunk_texts)))
        body = CHUNK_SEPARATOR.join(chunk_texts)
        return body, idxs

    bm25_candidates = bm25_top(chunk_texts, subtopic, BM25_TOP)
    [subtopic_emb] = embed_batch(embed_client, [subtopic])
    scored = sorted(
        bm25_candidates,
        key=lambda i: cosine(subtopic_emb, corpus.chunks[i].embedding),
        reverse=True,
    )
    top_idxs = sorted(scored[:RERANK_TOP_K])  # source order for readability
    body = CHUNK_SEPARATOR.join(corpus.chunks[i].text for i in top_idxs)
    return body, top_idxs


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--book", help="Limit to one book .txt filename")
    parser.add_argument("--subtopic", help="Limit to one subtopic string")
    parser.add_argument("--dry-run", action="store_true", help="Skip uploads")
    args = parser.parse_args()

    pairs = load_subtopic_book_pairs()
    if args.book:
        pairs = {k: v for k, v in pairs.items() if k == args.book}
        if not pairs:
            print(f"No subtopics map to book {args.book!r}")
            return 1
    if args.subtopic:
        pairs = {k: {s for s in v if s == args.subtopic} for k, v in pairs.items()}
        pairs = {k: v for k, v in pairs.items() if v}
        if not pairs:
            print(f"No books map to subtopic {args.subtopic!r}")
            return 1

    print(f"Books to process: {len(pairs)}")
    total_subtopics = sum(len(v) for v in pairs.values())
    print(f"Excerpts to build: {total_subtopics}")

    embed_client = _embed_client()
    written = 0
    skipped_identical = 0
    failed: list[str] = []

    with httpx.Client() as http:
        for book, subtopics in pairs.items():
            print(f"\n=== {book} ({len(subtopics)} subtopic(s)) ===")
            try:
                corpus = load_or_build_corpus(
                    book, http=http, embed_client=embed_client, dry_run=args.dry_run
                )
            except Exception as exc:
                print(f"  ! failed to build corpus: {exc}")
                failed.append(book)
                continue
            if corpus is None:
                continue

            for subtopic in sorted(subtopics):
                excerpt_path = _excerpt_filename(book, subtopic)
                try:
                    body, idxs = build_excerpt_body(
                        corpus, subtopic, embed_client=embed_client
                    )
                except Exception as exc:
                    print(f"  ! [{subtopic!r}] retrieval failed: {exc}")
                    failed.append(f"{book}::{subtopic}")
                    continue

                new_body = body.encode("utf-8")
                existing = fetch_text(excerpt_path, http)
                if existing is not None and existing.encode("utf-8") == new_body:
                    skipped_identical += 1
                    print(f"  = {excerpt_path}  unchanged (chunks {idxs})")
                    continue

                upload(
                    excerpt_path,
                    new_body,
                    "text/plain; charset=utf-8",
                    http,
                    dry_run=args.dry_run,
                )
                written += 1
                print(
                    f"  ✓ {excerpt_path}  ({len(new_body)} bytes, chunks {idxs})"
                )

    print("\n=== Summary ===")
    print(f"  Excerpts written:   {written}")
    print(f"  Excerpts unchanged: {skipped_identical}")
    print(f"  Failures:           {len(failed)}")
    for f in failed:
        print(f"    - {f}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
