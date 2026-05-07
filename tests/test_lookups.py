from app.crews.assignment_crew.crew import lookup_evaluation_document
from app.crews.notes_crew.crew import lookup_reading_materials as notes_materials
from app.crews.quiz_crew.crew import lookup_reading_materials as quiz_materials


def test_assignment_evaluation_doc_known():
    assert lookup_evaluation_document("Film Analysis") == "IDS SEM I-Film diary.txt"


def test_assignment_evaluation_doc_unknown():
    assert lookup_evaluation_document("nonexistent") == "(none assigned)"


def test_notes_and_quiz_materials_differ_for_same_subtopic():
    """Both crews preserve their distinct n8n-era titles (notes uses pretty
    book names, quiz uses the raw filename slugs) — only the extension is
    normalized to .txt so the curriculum bucket lookup is a single hop."""

    n = notes_materials("film analysis")
    q = quiz_materials("film analysis")
    assert n and q
    assert all(item.endswith(".txt") or item.startswith("http") for item in n)
    assert all(item.endswith(".txt") or item.startswith("http") for item in q)
    assert n != q
