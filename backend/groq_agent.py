import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"

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


def model_name() -> str:
    return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY must be set in .env")
        _client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=120.0)
    return _client


async def llm_available() -> bool:
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


async def answer(farmer: str, field: str, message: str, memories: list[dict]) -> dict:
    if memories:
        memory_lines = "\n".join(f"- [{m['type']}] {m['text']}" for m in memories)
    else:
        memory_lines = "(no relevant field memories found)"

    user_prompt = (
        f"Farmer: {farmer}\n"
        f"Field: {field}\n"
        f"Farmer's message: {message}\n"
        f"\nRelevant recalled Hindsight memories:\n{memory_lines}\n"
        f"\n{OUTPUT_INSTRUCTION}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    client = get_client()
    content = ""
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
