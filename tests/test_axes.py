"""6-axis judge core tests (T3a): composite, threshold, parsing, back-compat."""

from agentforce_probe import judge as judge_mod
from agentforce_probe import scorer


def _all(v):
    return {k: v for k in judge_mod.JUDGE_AXES}


# ── composite_score ────────────────────────────────────────────────────────────


def test_composite_all_one():
    assert judge_mod.composite_score(_all(1.0)) == 1.0


def test_composite_all_zero():
    assert judge_mod.composite_score(_all(0.0)) == 0.0


def test_composite_is_mean_of_present():
    axes = {
        "factualAccuracy": 0.0,
        "completeness": 1.0,
        "citationQuality": 1.0,
        "answerStructure": 1.0,
        "instructionAdherence": 1.0,
        "answerRelevance": 1.0,
    }
    assert round(judge_mod.composite_score(axes), 3) == 0.833


def test_composite_ignores_missing_keys():
    # only two axes present -> mean of those two
    axes = {"factualAccuracy": 0.4, "completeness": 0.6}
    assert round(judge_mod.composite_score(axes), 3) == 0.5


def test_composite_no_axes_is_zero():
    assert judge_mod.composite_score({}) == 0.0


# ── axes_to_verdict ─────────────────────────────────────────────────────────────


def test_verdict_at_threshold_passes():
    # comfortably above threshold (avoid float-equality at the exact boundary)
    assert judge_mod.axes_to_verdict(_all(0.8)) is True


def test_verdict_below_threshold_fails():
    assert judge_mod.axes_to_verdict(_all(0.5)) is False


def test_verdict_low_factual_drags_composite_to_fail():
    # one axis at 0 with the rest at 0.6 -> mean 0.5 -> FAIL
    axes = {
        "factualAccuracy": 0.0,
        "completeness": 0.6,
        "citationQuality": 0.6,
        "answerStructure": 0.6,
        "instructionAdherence": 0.6,
        "answerRelevance": 0.6,
    }
    assert judge_mod.axes_to_verdict(axes) is False


# ── hybrid veto: conjunctive hard gate over the compensatory mean ───────────────


def test_veto_fabricated_but_fluent_fails():
    """THE HOLE the hybrid gate closes: a fabricated answer (factualAccuracy=0.0)
    that is otherwise beautifully written (everything else 0.9). The old
    unweighted mean = (0.0 + 0.9*5)/6 = 0.75 >= 0.7 -> would PASS. The veto must
    FAIL it regardless of how polished the prose is."""
    axes = {
        "factualAccuracy": 0.0,
        "completeness": 0.9,
        "citationQuality": 0.9,
        "answerStructure": 0.9,
        "instructionAdherence": 0.9,
        "answerRelevance": 0.9,
    }
    # the compensatory mean alone would have passed it ...
    assert judge_mod.composite_score(axes) >= judge_mod.PASS_THRESHOLD
    # ... but the veto fails it.
    assert judge_mod.axes_to_verdict(axes) is False
    assert judge_mod.vetoed(axes) == "factualAccuracy"


def test_veto_low_instruction_adherence_fails():
    """instructionAdherence below the floor (e.g. a security-gate breach) vetoes
    even with high factualAccuracy and a high mean."""
    axes = {
        "factualAccuracy": 0.9,
        "completeness": 0.9,
        "citationQuality": 0.9,
        "answerStructure": 0.9,
        "instructionAdherence": 0.1,
        "answerRelevance": 0.9,
    }
    assert judge_mod.composite_score(axes) >= judge_mod.PASS_THRESHOLD
    assert judge_mod.axes_to_verdict(axes) is False
    assert judge_mod.vetoed(axes) == "instructionAdherence"


def test_veto_does_not_fire_above_floor():
    """A low-but-above-floor critical axis does NOT veto; the compensatory mean
    decides. factualAccuracy=0.4 (>= 0.3 floor) with the rest at 0.9 -> mean
    ~0.82 -> PASS."""
    axes = {
        "factualAccuracy": 0.4,
        "completeness": 0.9,
        "citationQuality": 0.9,
        "answerStructure": 0.9,
        "instructionAdherence": 0.9,
        "answerRelevance": 0.9,
    }
    assert judge_mod.vetoed(axes) is None
    assert judge_mod.axes_to_verdict(axes) is True


def test_veto_absent_axis_cannot_veto():
    """You can't fail a gate that wasn't measured: a missing factualAccuracy
    must not trigger a veto."""
    axes = {"completeness": 0.8, "answerRelevance": 0.8}
    assert judge_mod.vetoed(axes) is None


def test_veto_passes_clean_high_scores():
    """A genuinely good answer (all axes high) still passes — the veto only
    catches critical-axis failures, it doesn't tighten the bar for good output."""
    assert judge_mod.vetoed(_all(0.9)) is None
    assert judge_mod.axes_to_verdict(_all(0.9)) is True


# ── _extract_verdict (6-axis JSON, old shape, garbage) ──────────────────────────


def test_extract_six_axis_json():
    text = (
        '{"factualAccuracy":0.9,"completeness":0.9,"citationQuality":0.9,'
        '"answerStructure":0.9,"instructionAdherence":0.9,"answerRelevance":0.9,'
        '"reason":"good"}'
    )
    passed, reason, axes = judge_mod._extract_verdict(text)
    assert passed is True
    assert reason == "good"
    assert axes is not None
    assert len(axes) >= 6


def test_extract_six_axis_below_threshold():
    text = (
        '{"factualAccuracy":0.1,"completeness":0.2,"citationQuality":0.2,'
        '"answerStructure":0.2,"instructionAdherence":0.2,"answerRelevance":0.2,'
        '"reason":"weak"}'
    )
    passed, reason, axes = judge_mod._extract_verdict(text)
    assert passed is False
    assert axes is not None


def test_extract_old_verdict_shape_back_compat():
    passed, reason, axes = judge_mod._extract_verdict('{"verdict":"PASS","reason":"x"}')
    assert passed is True
    assert reason == "x"
    assert axes is None


def test_extract_old_verdict_fail():
    passed, reason, axes = judge_mod._extract_verdict('{"verdict":"FAIL","reason":"nope"}')
    assert passed is False
    assert axes is None


def test_extract_garbage_falls_back():
    passed, reason, axes = judge_mod._extract_verdict("not json at all")
    assert axes is None
    assert isinstance(passed, bool)


# ── judge_case returns a 3-tuple ────────────────────────────────────────────────


def test_judge_case_mock_three_tuple_axes_none():
    passed, reason, axes = judge_mod.judge_case("mock", "", None, "u", "expected", "a reply")
    assert isinstance(passed, bool)
    assert axes is None  # mock is ungrounded — no axis scores


# ── scorer carries axes ─────────────────────────────────────────────────────────


def test_score_case_stores_axes():
    axes = _all(0.8)
    r = scorer.score_case({"utterance": "x", "expectedOutcome": "o"}, 1, output_pass=True, axes=axes)
    assert r["axes"] == axes


def test_score_case_axes_default_none():
    r = scorer.score_case({"utterance": "x", "expectedOutcome": "o"}, 1, output_pass=True)
    assert r["axes"] is None
