"""Token-hygiene tests: the diagnostic descriptor must never leak token bytes."""
from agentforce_probe import agent_api


def test_token_shape_never_returns_token_bytes():
    fake = "header." + ("a" * 900) + ".sig"
    shape = agent_api.token_shape(fake)
    # descriptor must only carry len / segments / a bool — never a substring.
    assert set(shape.keys()) == {"len", "segments", "looks_like_jwt"}
    assert shape["segments"] == 3
    assert shape["looks_like_jwt"] is True
    for v in shape.values():
        assert fake not in str(v)


def test_opaque_token_flagged_not_jwt():
    shape = agent_api.token_shape("short-opaque-token")
    assert shape["looks_like_jwt"] is False


def test_empty_token():
    shape = agent_api.token_shape("")
    assert shape == {"len": 0, "segments": 0, "looks_like_jwt": False}
