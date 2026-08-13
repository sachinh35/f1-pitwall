"""
Real, no-mocks end-to-end run of the team-radio pipeline's two external-service legs:

1. Whisper transcription against a genuinely downloaded speech recording (not synthesized
   text) - tests/fixtures/audio/public_domain_speech_sample.wav, an 8-second public-domain
   clip trimmed from "Marcus Garvey, speech, 1921.ogg" on Wikimedia Commons (Public Domain
   Mark 1.0 - confirmed via the Commons API before committing it; not an F1 broadcast clip,
   since those are copyrighted, but this is real recorded human speech, which is exactly
   what's needed to prove the Whisper leg of the pipeline actually works end-to-end).
2. A real Gemini call through utils/radio_analysis.py, using realistic F1-radio-style
   transcript text (the sample audio above isn't F1 radio, so it can't exercise the
   notability prompt meaningfully - constructed text is used for that leg instead, same
   as how the prompt itself was iterated against real Gemini calls during development).

Both legs are skipped (not failed) when their prerequisite isn't available locally -
this file must never block a contributor without a Whisper model or a Gemini API key from
running the rest of the suite, and must never run in a CI environment that has neither.
"""
from pathlib import Path

import httpx
import pytest
from google.genai.errors import ClientError

from config.gemini_config import GeminiConfig
from utils.radio_analysis import RadioMessageAnalysis, analyze_transcript
from utils.team_radio_pipeline import resolve_audio_url
from utils.whisper_transcriber import DEFAULT_MODELS_DIR, DEFAULT_MODEL_NAME

AUDIO_FIXTURE = Path(__file__).parent / "fixtures" / "audio" / "public_domain_speech_sample.wav"
_WHISPER_MODEL_AVAILABLE = (DEFAULT_MODELS_DIR / f"ggml-{DEFAULT_MODEL_NAME}.bin").exists()


async def _analyze_or_skip(**kwargs) -> RadioMessageAnalysis:
    """analyze_transcript(), but skip (not fail) when GEMINI_API_KEY is set but rejected by
    the API (expired/revoked key) - same "never block a contributor" intent as the
    skipif(not GeminiConfig.API_KEY, ...) guards below, extended to cover a present-but-dead
    key, which skipif alone can't detect without making a real call."""
    try:
        return await analyze_transcript(**kwargs)
    except ClientError as exc:
        if exc.code == 401:
            pytest.skip(f"GEMINI_API_KEY is set but rejected by the Gemini API (401): {exc}")
        raise


@pytest.mark.skipif(not _WHISPER_MODEL_AVAILABLE, reason="No local Whisper model cached - see whisper_transcriber.py")
@pytest.mark.asyncio
async def test_whisper_transcribes_a_real_downloaded_speech_sample() -> None:
    from utils.whisper_transcriber import transcribe

    assert AUDIO_FIXTURE.exists(), f"missing audio fixture: {AUDIO_FIXTURE}"

    transcript = await transcribe(AUDIO_FIXTURE)

    # Not asserting exact wording (Whisper's output can vary slightly run to run) - asserting
    # it produced substantial, real, non-empty text is the meaningful end-to-end proof that
    # download -> ffmpeg-decodable audio -> Whisper actually works, not a placeholder/mock.
    assert isinstance(transcript, str)
    assert len(transcript.split()) >= 5


@pytest.mark.skipif(not GeminiConfig.API_KEY, reason="GEMINI_API_KEY not set - copy .env.example to .env")
@pytest.mark.asyncio
async def test_gemini_agent_flags_a_real_box_call_as_notable() -> None:
    result = await _analyze_or_skip(
        driver_label="Max Verstappen (VER)",
        lap_number=34,
        transcript="Box box box, box this lap, we are pitting for the medium tyre.",
    )

    assert result.speaker_role in ("pit_wall", "driver", "unclear")
    assert result.is_notable is True
    assert result.notable_reason


@pytest.mark.skipif(not GeminiConfig.API_KEY, reason="GEMINI_API_KEY not set - copy .env.example to .env")
@pytest.mark.asyncio
async def test_gemini_agent_does_not_flag_a_routine_acknowledgement() -> None:
    result = await _analyze_or_skip(
        driver_label="Lando Norris (NOR)", lap_number=12, transcript="Copy that, understood."
    )

    assert result.is_notable is False


def test_resolve_audio_url_downloads_a_real_historical_team_radio_clip() -> None:
    """
    Proves resolve_audio_url's session_path-aware URL construction against F1's real,
    unauthenticated static CDN - not a mock, not a guess. This exact URL shape was
    discovered by empirically confirming a bare `{base}/{relative_path}` URL 403s (raw
    S3/CloudFront AccessDenied) while this session_path-rooted form returns a real,
    valid MPEG audio file. Uses a path captured in a real historical race log
    (f1_stream_1764517880_race_qatar.jsonl), so this also incidentally proves the fix
    for every session already captured in stream_logs/, not just future ones.
    """
    url = resolve_audio_url(
        "TeamRadio/MAXVER01_1_20251130_191032.mp3",
        session_path="2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/",
    )
    try:
        response = httpx.get(url, timeout=15.0)
    except httpx.TransportError:
        pytest.skip("No network access to F1's live timing CDN")

    assert response.status_code == 200
    assert response.content[:2] in (b"ID3", b"\xff\xfb")  # MP3 header (ID3 tag or raw MPEG frame sync)
    assert len(response.content) > 10_000  # a real clip, not an error page


@pytest.mark.skipif(
    not (_WHISPER_MODEL_AVAILABLE and GeminiConfig.API_KEY),
    reason="Requires both a local Whisper model and GEMINI_API_KEY",
)
@pytest.mark.asyncio
async def test_full_pipeline_transcribe_then_classify_end_to_end() -> None:
    """The two legs chained together exactly as utils/team_radio_pipeline.py runs them:
    real audio in, real transcript out, real transcript in, real classification out."""
    from utils.whisper_transcriber import transcribe

    transcript = await transcribe(AUDIO_FIXTURE)
    assert transcript

    result = await _analyze_or_skip(driver_label="Driver #1", lap_number=1, transcript=transcript)

    assert result.speaker_role in ("driver", "pit_wall", "unclear")
    assert isinstance(result.is_notable, bool)
