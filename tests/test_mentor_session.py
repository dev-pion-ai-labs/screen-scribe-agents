from app.crews.mentor_crew.crew import (
    HISTORY_LIMIT,
    _append_turn,
    _format_history,
    _get_history,
)


def test_history_isolated_per_session():
    _append_turn("session-A", "hello", "hi A")
    _append_turn("session-B", "hello", "hi B")

    a = _get_history("session-A")
    b = _get_history("session-B")
    assert a[-1] == ("mentor", "hi A")
    assert b[-1] == ("mentor", "hi B")


def test_no_session_id_means_no_history():
    _append_turn(None, "hello", "ignored")
    assert _get_history(None) == []


def test_history_capped_at_limit():
    sid = "session-cap"
    for i in range(HISTORY_LIMIT * 2):
        _append_turn(sid, f"q{i}", f"a{i}")
    history = _get_history(sid)
    assert len(history) == HISTORY_LIMIT


def test_format_empty_history():
    assert "no prior messages" in _format_history([]).lower()
