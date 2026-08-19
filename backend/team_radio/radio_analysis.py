"""
Classifies a team-radio transcript via a Strands Agent backed by Google Gemini: who's
most likely speaking (driver vs pit wall - F1's raw feed carries no speaker/diarization
info at all, so this is an LLM inference over the transcript text, not ground truth) and
whether the message is notable enough to surface in the "Notable Radio" widget (box
calls, incidents, overtakes, retirements, etc.), with a short reason why.

Kept as a thin, mockable wrapper around one function, analyze_transcript() - tests
monkeypatch _get_agent() rather than hitting the real Gemini API (see
tests/test_radio_analysis.py). The prompt below was iterated against real Gemini calls
(not written blind) - notably, an early version scored a routine-sounding box/pit call as
NOT notable, which is wrong given box calls are explicitly always broadcast-worthy in F1;
rule (1) below exists specifically to correct that.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field
from strands import Agent
from strands.models.gemini import GeminiModel

from config.gemini_config import GeminiConfig

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an F1 broadcast producer reviewing team radio transcripts to decide which ones
deserve an on-screen highlight. ALWAYS mark is_notable=true for ANY of these, even if they sound
routine or calm: (1) any box/pit call or pit strategy instruction - pit stops are always
broadcast-worthy in F1, no exceptions; (2) overtakes or attempted overtakes; (3) collisions, incidents,
or contact; (4) penalties or investigations; (5) mechanical problems, damage, or retirements; (6) safety
car, red flag, or VSC; (7) strong emotional reactions (anger, celebration); (8) any other tactical or
strategic instruction. Mark is_notable=false ONLY for pure acknowledgements with zero new information
("copy", "understood", "yep"), static/unintelligible fragments, or generic well-being check-ins.
When in doubt, prefer true."""


class RadioMessageAnalysis(BaseModel):
    speaker_role: Literal["driver", "pit_wall", "unclear"] = Field(
        description="Who is most likely speaking in this transcript"
    )
    reasoning: str = Field(description="One short sentence of reasoning about the content, before deciding notability")
    is_notable: bool = Field(description="True if this radio message would be exciting or important to a race fan")
    notable_reason: Optional[str] = Field(default=None, description="One short sentence why, if notable, else null")


_agent: Optional[Agent] = None


def _get_agent() -> Agent:
    """Lazily construct the singleton Strands Agent - not at import time, so importing this
    module never requires GEMINI_API_KEY to be set (only actually calling analyze_transcript does)."""
    global _agent
    if _agent is None:
        if not GeminiConfig.API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set - copy .env.example to .env and fill it in")
        model = GeminiModel(
            client_args={"api_key": GeminiConfig.API_KEY},
            model_id=GeminiConfig.MODEL_ID,
            params={"temperature": 0.2, "max_output_tokens": 512},
        )
        _agent = Agent(model=model)
    return _agent


def _analyze_sync(driver_label: str, lap_number: Optional[int], transcript: str) -> RadioMessageAnalysis:
    agent = _get_agent()
    lap_text = f"Lap: {lap_number}." if lap_number is not None else "Lap: unknown."
    prompt = f'Driver: {driver_label}. {lap_text}\nTranscript: "{transcript}"'
    result = agent(prompt, system_prompt=_SYSTEM_PROMPT, structured_output_model=RadioMessageAnalysis)
    return result.structured_output


async def analyze_transcript(driver_label: str, lap_number: Optional[int], transcript: str) -> RadioMessageAnalysis:
    """
    Classify one team-radio transcript. The Strands agent call is synchronous/blocking
    (network I/O), so this runs it in the default executor rather than awaiting it
    directly, to avoid blocking the event loop that's simultaneously processing live
    timing messages - same reasoning as whisper_transcriber.transcribe().
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _analyze_sync, driver_label, lap_number, transcript)
