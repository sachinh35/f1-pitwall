"""
Unit tests for utils/radio_analysis.py. The real Gemini API is never called here -
_get_agent (or the module-level GeminiConfig it depends on) is monkeypatched throughout.
See tests/test_radio_analysis_e2e.py for a real-API/real-audio end-to-end run.
"""
from unittest.mock import MagicMock

import pytest

from utils import radio_analysis
from utils.radio_analysis import GeminiConfig, RadioMessageAnalysis, analyze_transcript


@pytest.fixture(autouse=True)
def _reset_agent_cache(monkeypatch: pytest.MonkeyPatch):
    """_get_agent caches its Agent in a module-level global - reset it before/after every
    test so one test's mock/config never leaks into another's."""
    monkeypatch.setattr(radio_analysis, "_agent", None)
    yield
    monkeypatch.setattr(radio_analysis, "_agent", None)


def _fake_agent(returned: RadioMessageAnalysis) -> MagicMock:
    agent = MagicMock()
    result = MagicMock()
    result.structured_output = returned
    agent.return_value = result
    return agent


# ---- _get_agent ----

def test_get_agent_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GeminiConfig, "API_KEY", None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        radio_analysis._get_agent()


def test_get_agent_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GeminiConfig, "API_KEY", "fake-key")
    constructed = []

    class _FakeAgent:
        def __init__(self, model):
            constructed.append(model)

    monkeypatch.setattr(radio_analysis, "Agent", _FakeAgent)
    monkeypatch.setattr(radio_analysis, "GeminiModel", MagicMock(return_value="fake-model"))

    first = radio_analysis._get_agent()
    second = radio_analysis._get_agent()

    assert first is second
    assert len(constructed) == 1


# ---- analyze_transcript ----

@pytest.mark.asyncio
async def test_analyze_transcript_returns_agents_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = RadioMessageAnalysis(
        speaker_role="pit_wall", reasoning="Box call.", is_notable=True, notable_reason="Pit stop."
    )
    fake_agent = _fake_agent(expected)
    monkeypatch.setattr(radio_analysis, "_get_agent", lambda: fake_agent)

    result = await analyze_transcript("Driver #1", 34, "Box box box, box this lap.")

    assert result == expected
    prompt, kwargs = fake_agent.call_args.args[0], fake_agent.call_args.kwargs
    assert "Driver #1" in prompt
    assert "Lap: 34." in prompt
    assert "Box box box, box this lap." in prompt
    assert kwargs["structured_output_model"] is RadioMessageAnalysis
    assert kwargs["system_prompt"] == radio_analysis._SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_analyze_transcript_handles_missing_lap_number(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = RadioMessageAnalysis(speaker_role="unclear", reasoning="x", is_notable=False, notable_reason=None)
    fake_agent = _fake_agent(expected)
    monkeypatch.setattr(radio_analysis, "_get_agent", lambda: fake_agent)

    await analyze_transcript("Driver #44", None, "static...")

    prompt = fake_agent.call_args.args[0]
    assert "Lap: unknown." in prompt


@pytest.mark.asyncio
async def test_analyze_transcript_propagates_agent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError("Gemini quota exceeded")

    fake_agent = MagicMock(side_effect=_raise)
    monkeypatch.setattr(radio_analysis, "_get_agent", lambda: fake_agent)

    with pytest.raises(RuntimeError, match="Gemini quota exceeded"):
        await analyze_transcript("Driver #1", 1, "hello")
