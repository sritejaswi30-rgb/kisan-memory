"""Multi-user isolation test for KisanMemory.

Proves that user 1001 (Ravi, Field A, tomato) and user 1002 (Sita, Field B,
paddy) cannot see each other's Hindsight memories, and that new experiences are
retained into the correct per-user bank.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import hindsight_client  # noqa: E402

BASE_URL = os.getenv("KISANMEMORY_URL", "http://127.0.0.1:8055")

RAVI = {"X-User-ID": "1001"}
SITA = {"X-User-ID": "1002"}

RAVI_LEAKS = ("paddy", "irrigation", "field b", "sita", "soil moisture", "treatment c", "treatment d")
SITA_LEAKS = ("tomato", "waterlogging", "treatment a", "fung", "ravi", "field a")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {label}: {'PASS' if condition else 'FAIL'} {detail}")
    if not condition:
        failures.append(label)


def joined(data: dict) -> str:
    return " ".join(memory["text"] for memory in data.get("memories_used", [])).lower()


def bank_texts(bank: str) -> list[str]:
    async def _run():
        try:
            items = await hindsight_client.recent_memories(bank=bank)
            return [item["text"] for item in items]
        finally:
            await hindsight_client.close()

    return asyncio.run(_run())


def chat(client: httpx.Client, headers: dict, field_id, message: str) -> tuple[int, dict]:
    response = client.post(
        "/chat", headers=headers, json={"field_id": field_id, "message": message}
    )
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {}


def main() -> int:
    print("MULTI-USER ISOLATION TEST")
    with httpx.Client(base_url=BASE_URL, timeout=300.0) as client:
        print("\n1) user context endpoints")
        ravi = client.get("/users/me", headers=RAVI).json()
        sita = client.get("/users/me", headers=SITA).json()
        check("Ravi resolved", ravi.get("name") == "Ravi", f"got {ravi.get('name')}")
        check("Ravi bank mapping", ravi.get("bank_id") == "kisan-user-1001", f"got {ravi.get('bank_id')}")
        check(
            "Ravi field",
            [field["name"] for field in ravi.get("fields", [])][:1] == ["Field A"]
            and ravi["fields"][0].get("crop") == "Tomato",
            str([field["name"] for field in ravi.get("fields", [])]),
        )
        check("Sita resolved", sita.get("name") == "Sita", f"got {sita.get('name')}")
        check("Sita bank mapping", sita.get("bank_id") == "kisan-user-1002", f"got {sita.get('bank_id')}")
        check(
            "Sita field",
            [field["name"] for field in sita.get("fields", [])][:1] == ["Field B"]
            and sita["fields"][0].get("crop") == "Paddy",
            str([field["name"] for field in sita.get("fields", [])]),
        )
        check("missing header rejected", client.get("/users/me").status_code == 400)
        check("unknown user rejected", client.get("/users/me", headers={"X-User-ID": "9999"}).status_code == 404)

        print("\n2) field endpoints")
        ravi_fields = client.get("/fields", headers=RAVI).json()
        sita_fields = client.get("/fields", headers=SITA).json()
        field_a = ravi_fields[0]
        field_b = sita_fields[0]
        check("Ravi sees Field A", field_a["name"] == "Field A")
        check("Sita sees Field B", field_b["name"] == "Field B")
        check(
            "fields are not shared",
            {field["name"] for field in ravi_fields}.isdisjoint(
                {field["name"] for field in sita_fields}
            ),
        )
        created = client.post(
            "/fields",
            headers=RAVI,
            json={"name": "Field C", "crop": "Maize", "planting_date": "2026-07-01"},
        )
        check("POST /fields creates a field", created.status_code == 201, f"HTTP {created.status_code}")
        check("created field belongs to Ravi", created.json().get("user_id") == "1001")
        check(
            "Sita cannot see Ravi's new field",
            "Field C" not in [field["name"] for field in client.get("/fields", headers=SITA).json()],
        )
        check(
            "cross-user field access denied",
            client.post(
                "/chat",
                headers=RAVI,
                json={"field_id": field_b["id"], "message": "hello"},
            ).status_code
            == 404,
        )

        print("\n3) snapshot Sita's bank before Ravi retains anything new")
        sita_before = sorted(bank_texts("kisan-user-1002"))
        check("Sita's bank has seeded memories", len(sita_before) >= 5, f"got {len(sita_before)}")

        print("\n4) Ravi asks about his tomato field")
        status, data = chat(client, RAVI, field_a["id"], "What happened after the heavy rain in my tomato field?")
        check("Ravi chat works", status == 200, f"HTTP {status}")
        check("Ravi user_id echoed", data.get("user_id") == "1001", str(data.get("user_id")))
        check("Ravi field_id echoed", data.get("field_id") == str(field_a["id"]), str(data.get("field_id")))
        check("Ravi recalled his memories", data.get("memory_count", 0) > 0, f"count={data.get('memory_count')}")
        ravi_text = joined(data)
        answer_ravi = data.get("response", "").lower()
        check("Ravi answer uses his history", "rain" in answer_ravi or "waterlog" in answer_ravi, answer_ravi[:90])
        leaks = [word for word in RAVI_LEAKS if word in ravi_text]
        check("Ravi sees none of Sita's memories", not leaks, f"leaks={leaks}")

        print("\n5) Sita asks about her paddy field")
        status, data = chat(
            client, SITA, field_b["id"], "What happened with irrigation and soil moisture in my paddy field?"
        )
        check("Sita chat works", status == 200, f"HTTP {status}")
        check("Sita user_id echoed", data.get("user_id") == "1002", str(data.get("user_id")))
        check("Sita recalled her memories", data.get("memory_count", 0) > 0, f"count={data.get('memory_count')}")
        sita_text = joined(data)
        answer_sita = data.get("response", "").lower()
        check(
            "Sita answer uses her history",
            any(word in answer_sita for word in ("irrigation", "soil moisture", "paddy")),
            answer_sita[:90],
        )
        leaks = [word for word in SITA_LEAKS if word in sita_text]
        check("Sita sees none of Ravi's memories", not leaks, f"leaks={leaks}")

        print("\n6) Ravi retains a new experience into his own bank")
        aphid_message = "I noticed a swarm of aphids on the tomato leaves in Field A today, please remember this."
        stored = 0
        for attempt in range(3):
            status, data = chat(client, RAVI, field_a["id"], aphid_message)
            if attempt == 0:
                check("Ravi report accepted", status == 200, f"HTTP {status}")
            stored = data.get("new_memories_stored", 0)
            if stored:
                break
        check("Ravi's new memory stored", stored >= 1, f"stored={stored}")

        ravi_bank: list[str] = []
        for _ in range(12):
            ravi_bank = bank_texts("kisan-user-1001")
            if any("aphid" in text.lower() for text in ravi_bank):
                break
            time.sleep(2)
        check(
            "new memory is in Ravi's bank",
            any("aphid" in text.lower() for text in ravi_bank),
            f"bank size={len(ravi_bank)}",
        )

        print("\n7) Sita cannot recall Ravi's new memory; her bank is unchanged")
        status, data = chat(client, SITA, field_b["id"], "Did I see aphids in Field A?")
        check("Sita chat works", status == 200, f"HTTP {status}")
        sita_after_chat = joined(data)
        check("Sita cannot recall Ravi's aphid memory", "aphid" not in sita_after_chat)
        sita_after = sorted(bank_texts("kisan-user-1002"))
        check("Sita's memories unchanged", sita_after == sita_before, f"before={len(sita_before)} after={len(sita_after)}")
        check("Sita's bank has no aphid memory", not any("aphid" in text.lower() for text in sita_after))
        check("Sita's bank has no tomato memory", not any("tomato" in text.lower() for text in sita_after))

    print("\n" + "=" * 44)
    print("ISOLATION RESULT:", "FAIL" if failures else "PASS")
    if failures:
        print("failed checks:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
