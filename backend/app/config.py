"""Application configuration, loaded from environment / backend/.env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

APP_NAME = "ClashDoctor"
APP_VERSION = "0.1.0"

QLOO_BASE_URL = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/")
QLOO_API_KEY = os.getenv("QLOO_API_KEY", "").strip()
QLOO_TIMEOUT_SECONDS = float(os.getenv("QLOO_TIMEOUT_SECONDS", "30"))
QLOO_INSIGHTS_TAKE = int(os.getenv("QLOO_INSIGHTS_TAKE", "20"))

# In-memory TTL cache lifetime for artist tag profiles (seconds).
PROFILE_CACHE_TTL_SECONDS = int(os.getenv("PROFILE_CACHE_TTL_SECONDS", "3600"))

# Demo artists use entity ids prefixed with this and never hit the Qloo API.
DEMO_ENTITY_PREFIX = "demo:"

# Imported acts with no confirmed Qloo match use this prefix. It is a local
# placeholder, never a Qloo entity id, and is never sent to the API.
UNMATCHED_ENTITY_PREFIX = "unmatched:"

# Optional language model for POST /api/plan/interpret. Any OpenAI-compatible
# /chat/completions endpoint that can answer with a JSON object. With no key and no
# model the endpoint uses its documented phrase rules instead, and says which it used
# in the response. Keys go in backend/.env, never in source.
PLANNER_BASE_URL = os.getenv("PLANNER_BASE_URL", "https://api.openai.com/v1").rstrip("/")
PLANNER_API_KEY = os.getenv("PLANNER_API_KEY", "").strip()
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "").strip()
PLANNER_TIMEOUT_SECONDS = float(os.getenv("PLANNER_TIMEOUT_SECONDS", "20"))
