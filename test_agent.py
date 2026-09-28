import os
import sys

import httpx

BASE_URL = os.getenv("KISANMEMORY_URL", "http://127.0.0.1:8055")

TESTS = [
    ("TEST 1", "What happened previously in Ravi's tomato field after heavy rain?"),
    ("TEST 2", "I tried Treatment A again this time, but it did not help."),
    ("TEST 3", "What have I learned from my previous experiences with this problem?"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failures = 0

    with httpx.Client(base_url=BASE_URL, timeout=300.0) as client:
        health = client.get("/health")
        health.raise_for_status()
        body = health.json()
        print(
            f"HEALTH: status={body['status']} "
            f"hindsight={body['hindsight']} llm={body['llm']}"
        )

        for label, message in TESTS:
            print("")
            print(f"{label}: {message}")
            try:
                response = client.post(
                    "/chat",
                    json={"farmer": "Ravi", "field": "Field A", "message": message},
                )
                if response.status_code != 200:
                    failures += 1
                    print(f"  ERROR: HTTP {response.status_code} {response.text}")
                    continue
                data = response.json()
                print(f"  response: {data['response']}")
                print(f"  memories recalled: {data['memory_count']}")
                print(f"  new memories stored: {data['new_memories_stored']}")
                for memory in data["memories_used"]:
                    print(f"    - [{memory['type']}] {memory['text']}")
            except httpx.HTTPError as error:
                failures += 1
                print(f"  ERROR: {error}")

    print("")
    print(f"RESULT: {'FAIL' if failures else 'PASS'} ({failures} failed request(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
