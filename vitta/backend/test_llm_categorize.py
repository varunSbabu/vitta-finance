"""Tests for Tier 3 LLM categorization fallback.

No real network calls — _call_groq is monkeypatched so these run offline
and don't need GROQ_API_KEY. What's under test is the batching, category
validation, and graceful-fallback behavior, not Groq itself.
"""

import os

import llm_categorize as lc


def test_unavailable_without_api_key():
    os.environ.pop("GROQ_API_KEY", None)
    assert lc.is_available() is False
    result = lc.categorize_batch([{"merchant": "X", "amount": 100}])
    assert result == [("Uncategorized", 0.0)]
    print("  OK no API key -> unavailable, fallback result, no crash")


def test_empty_input_returns_empty():
    assert lc.categorize_batch([]) == []
    print("  OK empty input returns empty list without calling the API")


def test_extract_json_array_plain():
    text = '[{"category": "Food", "confidence": 0.9}]'
    parsed = lc._extract_json_array(text)
    assert parsed == [{"category": "Food", "confidence": 0.9}]
    print("  OK plain JSON array extraction")


def test_extract_json_array_with_surrounding_prose():
    text = 'Here is the result:\n[{"category": "Food", "confidence": 0.9}]\nHope that helps!'
    parsed = lc._extract_json_array(text)
    assert parsed == [{"category": "Food", "confidence": 0.9}]
    print("  OK JSON array extracted despite surrounding prose")


def test_extract_json_array_malformed_returns_empty():
    assert lc._extract_json_array("not json at all") == []
    assert lc._extract_json_array("[{broken json") == []
    print("  OK malformed content returns empty list instead of raising")


def test_call_groq_validates_categories(monkeypatch):
    os.environ["GROQ_API_KEY"] = "fake-key-for-test"

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '[{"category": "Food", "confidence": 0.85}, '
                            '{"category": "MadeUpCategory", "confidence": 0.9}, '
                            '{"category": "Transport", "confidence": "not-a-number"}]'
                        }
                    }
                ]
            }

    monkeypatch.setattr(lc.requests, "post", lambda *a, **k: FakeResponse())

    items = [
        {"merchant": "Zomato", "amount": 300},
        {"merchant": "Weird Merchant", "amount": 50},
        {"merchant": "Some Cab Co", "amount": 120},
    ]
    result = lc.categorize_batch(items)

    assert result[0] == ("Food", 0.85)
    # Category not in the fixed CATEGORIES list must be rejected, not passed through
    assert result[1] == ("Uncategorized", 0.0)
    # Non-numeric confidence must fail safe (0.0) rather than crash — category
    # label survives since it was valid, but 0.0 confidence means main.py's
    # threshold check will never apply it anyway.
    assert result[2] == ("Transport", 0.0)
    print("  OK category whitelist enforced + malformed confidence fails safe")

    del os.environ["GROQ_API_KEY"]


def test_call_groq_network_failure_falls_back(monkeypatch):
    os.environ["GROQ_API_KEY"] = "fake-key-for-test"

    def raise_error(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(lc.requests, "post", raise_error)

    items = [{"merchant": "X", "amount": 100}, {"merchant": "Y", "amount": 200}]
    result = lc.categorize_batch(items)
    assert result == [("Uncategorized", 0.0), ("Uncategorized", 0.0)]
    print("  OK network failure falls back cleanly, one entry per input item")

    del os.environ["GROQ_API_KEY"]


def test_batching_splits_large_input(monkeypatch):
    os.environ["GROQ_API_KEY"] = "fake-key-for-test"
    call_count = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            call_count["n"] += 1
            n_items = call_count["chunk_size"]
            items = [{"category": "Food", "confidence": 0.9} for _ in range(n_items)]
            import json as _json

            return {"choices": [{"message": {"content": _json.dumps(items)}}]}

    def fake_post(url, headers, json, timeout):
        call_count["chunk_size"] = json["messages"][0]["content"].count("merchant=")
        return FakeResponse()

    monkeypatch.setattr(lc.requests, "post", fake_post)

    items = [{"merchant": f"M{i}", "amount": i} for i in range(lc.MAX_ITEMS_PER_CALL + 5)]
    result = lc.categorize_batch(items)
    assert len(result) == len(items)
    assert call_count["n"] == 2  # split into two API calls
    print(f"  OK {len(items)} items split into 2 batched calls, all results returned")

    del os.environ["GROQ_API_KEY"]


if __name__ == "__main__":

    class _Monkeypatch:
        def __init__(self):
            self._orig = {}

        def setattr(self, obj, name, value):
            self._orig[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)

        def undo(self):
            for (obj, name), value in self._orig.items():
                setattr(obj, name, value)

    tests = [
        test_unavailable_without_api_key,
        test_empty_input_returns_empty,
        test_extract_json_array_plain,
        test_extract_json_array_with_surrounding_prose,
        test_extract_json_array_malformed_returns_empty,
        test_call_groq_validates_categories,
        test_call_groq_network_failure_falls_back,
        test_batching_splits_large_input,
    ]
    passed = 0
    for t in tests:
        mp = _Monkeypatch()
        try:
            if "monkeypatch" in t.__code__.co_varnames[: t.__code__.co_argcount]:
                t(mp)
            else:
                t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e!r}")
        finally:
            mp.undo()
    print(f"\n{passed}/{len(tests)} tests passed")
