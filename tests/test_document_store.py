"""Tests for the subtopic-aware curriculum fetch path."""

from __future__ import annotations

import pytest

from app.services import document_store
from app.services.document_store import (
    _excerpt_filename,
    _subtopic_slug,
    get_document_text,
)


# ---------------------------------------------------------------------------
# Slug + excerpt filename helpers
# ---------------------------------------------------------------------------


def test_subtopic_slug_basic():
    assert _subtopic_slug("Film Analysis") == "film-analysis"


def test_subtopic_slug_collapses_punctuation():
    assert _subtopic_slug("i, a, l, c, s patterns") == "i-a-l-c-s-patterns"


def test_subtopic_slug_strips_unicode_runs():
    # `è` is non-alnum under [A-Za-z0-9], so it gets replaced.
    assert _subtopic_slug("Mise en Scène") == "mise-en-sc-ne"


def test_subtopic_slug_caps_at_80_chars():
    out = _subtopic_slug("a" * 200)
    assert len(out) == 80


def test_subtopic_slug_strips_trailing_dashes():
    assert _subtopic_slug("hello!!!") == "hello"
    assert not _subtopic_slug("!!!").endswith("-")


def test_excerpt_filename_strips_txt_and_joins():
    out = _excerpt_filename(
        "How to Read a Film_ Movies, Media, and Beyond.txt", "film analysis"
    )
    assert out == "how-to-read-a-film-movies-media-and-beyond__film-analysis.txt"


def test_excerpt_filename_handles_no_extension():
    out = _excerpt_filename("foo bar", "baz qux")
    assert out == "foo-bar__baz-qux.txt"


# ---------------------------------------------------------------------------
# Fetch behaviour: excerpt-first, fall back to whole-book
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    document_store._CACHE.clear()
    yield
    document_store._CACHE.clear()


@pytest.fixture
def fake_fetch(monkeypatch):
    """Patch fetch_plain_text with a recording stub. Caller fills `bodies`."""

    bodies: dict[str, str] = {}
    calls: list[str] = []

    async def stub(url: str) -> str:
        calls.append(url)
        for filename, body in bodies.items():
            if filename in url:
                return body
        # No mapping = simulate 404/empty body.
        return ""

    monkeypatch.setattr(document_store, "fetch_plain_text", stub)
    return bodies, calls


@pytest.mark.asyncio
async def test_fetch_uses_excerpt_when_available(fake_fetch):
    bodies, calls = fake_fetch
    bodies["foo__film-analysis.txt"] = "EXCERPT BODY"
    bodies["Foo.txt"] = "WHOLE BOOK BODY"

    text = await get_document_text("Foo.txt", subtopic="Film Analysis")
    assert text == "EXCERPT BODY"
    # Only the excerpt URL was fetched — no wasted call to the whole book.
    assert len(calls) == 1
    assert "foo__film-analysis.txt" in calls[0]


@pytest.mark.asyncio
async def test_fetch_falls_back_to_whole_book_on_excerpt_404(fake_fetch):
    bodies, calls = fake_fetch
    # No excerpt body registered → stub returns "" for it.
    bodies["Foo.txt"] = "WHOLE BOOK BODY"

    text = await get_document_text("Foo.txt", subtopic="Film Analysis")
    assert text == "WHOLE BOOK BODY"
    assert len(calls) == 2
    assert "foo__film-analysis.txt" in calls[0]
    assert calls[1].endswith("Foo.txt")


@pytest.mark.asyncio
async def test_fetch_without_subtopic_skips_excerpt_path(fake_fetch):
    bodies, calls = fake_fetch
    bodies["Foo.txt"] = "WHOLE BOOK BODY"

    text = await get_document_text("Foo.txt")
    assert text == "WHOLE BOOK BODY"
    assert len(calls) == 1
    assert "Foo.txt" in calls[0]


@pytest.mark.asyncio
async def test_url_entries_skipped(fake_fetch):
    bodies, calls = fake_fetch
    text = await get_document_text("https://example.com/x", subtopic="anything")
    assert text == ""
    assert calls == []


@pytest.mark.asyncio
async def test_cache_is_keyed_by_physical_filename(fake_fetch):
    """Two subtopics that both fall back to the same whole-book share the cache."""
    bodies, calls = fake_fetch
    bodies["Foo.txt"] = "WHOLE BOOK BODY"

    a = await get_document_text("Foo.txt", subtopic="alpha")
    b = await get_document_text("Foo.txt", subtopic="beta")
    assert a == b == "WHOLE BOOK BODY"
    # Each subtopic tries its own (missing) excerpt URL, but the whole-book
    # fetch happens only once because cache is keyed on physical filename.
    whole_book_calls = [c for c in calls if c.endswith("Foo.txt")]
    assert len(whole_book_calls) == 1
