import asyncio
import json
import os
import re

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-3.7-flash,gemini-flash-lite-latest"

SYSTEM_PROMPT = (
    "You are KisanMemory, a farmer's long-term field-memory assistant.\n"
    "\n"
    "Your most important capability is using the farmer's own historical experiences.\n"
    "\n"
    "Rules:\n"
    "- Use recalled Hindsight memories whenever relevant.\n"
    "- Clearly distinguish remembered history from general knowledge.\n"
    "- Never invent an historical event.\n"
    "- If relevant memory is missing, say that the history does not contain enough information.\n"
    "- When discussing a farming problem, first explain what the farmer experienced previously.\n"
    "- Prefer field-specific history over generic advice.\n"
    "- Do not present pesticide, chemical, dosage, or medical-style instructions as authoritative prescriptions.\n"
    "- Never tell the farmer to apply a chemical, increase a dosage, or use a specific pesticide product.\n"
    "- Ground statements in the farmer's record with phrasing like 'Your field history shows...',\n"
    "  'Previously, this outcome occurred...', 'Based on your recorded history...'.\n"
    "- If the prompt gives a current field crop and the farmer asks about a different crop,\n"
    "  answer that this field is recorded with that crop and that no planting record exists\n"
    "  for the other crop on this field.\n"
    "- Do not claim certainty from memory alone.\n"
    "- Be concise and practical.\n"
    "- Make the memory usage visible in the response.\n"
    "- Answer in the farmer's language when requested."
)

OUTPUT_INSTRUCTION = (
    "Respond with ONLY a JSON object, no other text, in this exact shape:\n"
    '{"answer": "...", "memory_facts_used": ["..."], "new_memory_candidates": ["..."]}\n'
    "\n"
    "- answer: your reply to the farmer.\n"
    "- memory_facts_used: the recalled memory texts you actually relied on (empty list if none).\n"
    "- new_memory_candidates: only NEW farmer/field experiences the farmer just reported "
    "(outcomes, field events, treatments attempted, results). Never include generic advice, "
    "assistant commentary, or anything that is not a farmer-reported experience. Empty list if none."
)

EMPTY_RESULT = {"answer": "", "memory_facts_used": [], "new_memory_candidates": []}

_client: AsyncOpenAI | None = None
_gemini_client: httpx.AsyncClient | None = None


def provider() -> str:
    """Active LLM provider: LLM_PROVIDER=gemini|groq (defaults to gemini when a
    Gemini key is present, otherwise groq)."""
    configured = os.getenv("LLM_PROVIDER", "").strip().lower()
    if configured in ("gemini", "groq"):
        return configured
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "gemini"
    return "groq"


def model_name() -> str:
    if provider() == "gemini":
        return gemini_models()[0]
    return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def gemini_models() -> list[str]:
    """Gemini models to try in order (GEMINI_MODEL may list several, e.g. when
    the primary free-tier model is rate-limited)."""
    configured = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    models = [name.strip() for name in configured.split(",") if name.strip()]
    return models or [DEFAULT_GEMINI_MODEL.split(",")[0]]


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY must be set in .env")
        _client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=120.0)
    return _client


def get_gemini_client() -> httpx.AsyncClient:
    global _gemini_client
    if _gemini_client is None:
        if not os.getenv("GEMINI_API_KEY", "").strip():
            raise RuntimeError("GEMINI_API_KEY must be set in .env")
        _gemini_client = httpx.AsyncClient(timeout=120.0)
    return _gemini_client


def _gemini_headers() -> dict:
    return {"x-goog-api-key": os.getenv("GEMINI_API_KEY", "").strip()}


async def _gemini_ping() -> bool:
    """List models (a free metadata call — no tokens generated)."""
    try:
        response = await get_gemini_client().get(
            f"{GEMINI_BASE_URL}/models",
            params={"pageSize": 1},
            headers=_gemini_headers(),
            timeout=30.0,
        )
        return response.status_code == 200
    except Exception:
        return False


async def llm_available() -> bool:
    if provider() == "gemini":
        return await _gemini_ping()
    try:
        await get_client().models.list()
        return True
    except Exception:
        return False


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_json(content: str) -> dict | None:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _normalize(data: dict | None, fallback_answer: str) -> dict:
    if not data:
        data = {}
    answer = str(data.get("answer") or "").strip() or fallback_answer
    return {
        "answer": answer,
        "memory_facts_used": _string_list(data.get("memory_facts_used")),
        "new_memory_candidates": _string_list(data.get("new_memory_candidates")),
    }


async def _gemini_generate(system: str, user_prompt: str, json_mode: bool) -> str:
    """Gemini generateContent call through the official REST API.

    Mirrors the Groq/OpenAI-compatible call: system instruction + one user turn,
    with an optional JSON output mode and a text fallback on retry. Each model in
    GEMINI_MODEL is retried with short backoff (free-tier 429/503 are common),
    then the next model in the list is tried.
    """
    payload: dict = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
    }
    if json_mode:
        payload["generationConfig"] = {"responseMimeType": "application/json"}

    headers = {**_gemini_headers(), "Content-Type": "application/json"}
    response: httpx.Response | None = None
    for model in gemini_models():
        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
        for attempt in range(3):
            response = await get_gemini_client().post(url, headers=headers, json=payload)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(3.0 * (attempt + 1))
                continue
            break
        if response.status_code == 200:
            break

    assert response is not None
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or [{}]
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(str(part.get("text") or "") for part in parts)


async def answer(
    farmer: str,
    field: str,
    message: str,
    memories: list[dict],
    crop: str | None = None,
    language: str | None = None,
) -> dict:
    if memories:
        memory_lines = "\n".join(f"- [{m['type']}] {m['text']}" for m in memories)
    else:
        memory_lines = "(no relevant field memories found)"

    crop_line = f"Current field crop: {crop}\n" if crop else ""
    language_line = f"Output language requested: {language}\n" if language else ""
    user_prompt = (
        f"Farmer: {farmer}\n"
        f"Field: {field}\n"
        f"{crop_line}"
        f"{language_line}"
        f"Farmer's message: {message}\n"
        f"\nRelevant recalled Hindsight memories:\n{memory_lines}\n"
        f"\n{OUTPUT_INSTRUCTION}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    content = ""
    if provider() == "gemini":
        try:
            content = await _gemini_generate(SYSTEM_PROMPT, user_prompt, json_mode=True)
        except Exception:
            content = await _gemini_generate(SYSTEM_PROMPT, user_prompt, json_mode=False)
    else:
        client = get_client()
        try:
            response = await client.chat.completions.create(
                model=model_name(),
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
        except Exception:
            response = await client.chat.completions.create(
                model=model_name(),
                messages=messages,
            )
            content = response.choices[0].message.content or ""

    if not content.strip():
        return dict(EMPTY_RESULT)

    return _normalize(_parse_json(content), fallback_answer=content.strip())
