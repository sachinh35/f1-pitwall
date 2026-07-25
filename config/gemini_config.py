"""
Gemini/Strands configuration - loaded from .env (see .env.example), following the same
env-var-with-default pattern as DatabaseConfig. .env is gitignored; only .env.example
(with a placeholder) is committed.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Explicit path (not a bare load_dotenv()) so this resolves the same regardless of the
# process's working directory when uvicorn/pytest is launched.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class GeminiConfig:
    """Configuration for the Strands Agent + Google Gemini team-radio classifier."""

    API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    MODEL_ID: str = os.getenv("GEMINI_MODEL_ID", "gemini-3.5-flash-lite")
