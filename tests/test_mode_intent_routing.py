import pytest
from agent.config.intent import ModeIntent, resolve


def intent(movement="walk", surface="ground", action="configure"):
    return ModeIntent(action=action, movement=movement, surface=surface)


@pytest.mark.parametrize("movement,surface,mode", [
    ("walk", "ground", "walking"), ("run", "ground", "overground_running"),
    ("walk", "treadmill", "treadmill_gait"), ("run", "treadmill", "treadmill_running"),
    ("jump", "unknown", "jump"),
])
def test_explicit_mode_overrides_selector(movement, surface, mode):
    assert resolve(intent(movement, surface), "jump", 1, "测试")["mode"] == mode


@pytest.mark.parametrize("segments", [None, 1, 8])
def test_ambiguous_never_generates_in_current_mode(segments):
    result = resolve(intent(surface="unknown"), "jump", segments, "走路5分钟")
    assert "message" not in result
    assert result["pending"]["message"] == "走路5分钟"
    assert result["pending"]["suggested_surface"] == ("ground" if segments == 8 else None)


def test_clarification_keeps_constraints():
    pending = resolve(intent(surface="unknown"), "jump", 8, "走路5分钟")["pending"]
    result = resolve(intent().model_copy(update={"uses_pending": True}), "jump", 8, "是", pending)
    assert result["mode"] == "walking"
    assert "5分钟" in result["message"]


def test_discussion_does_not_switch_and_incompatible_does_not_substitute():
    assert resolve(intent(action="discuss"), "jump", 8, "比较")["mode"] == "jump"
    result = resolve(intent(surface="treadmill"), "jump", 8, "跑步机走路")
    assert result["mode"] == "treadmill_gait" and "message" not in result
