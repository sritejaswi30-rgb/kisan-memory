"""Phase 1 connectivity test for KisanMemory.

Proves that we can genuinely connect to Hindsight Cloud, retain one farmer
memory, and recall it later. No application, UI, or backend in this phase.
"""

import os
import sys
import time

from dotenv import load_dotenv
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ApiException

MEMORY = (
    "Farmer Ravi planted tomatoes in Field A on June 5. "
    "After heavy rain on June 18, waterlogging was observed and fungal "
    "symptoms appeared on June 23. Ravi applied Treatment A on June 24, "
    "and the symptoms reduced by July 2."
)

QUERY = "What happened previously in Ravi's tomato field after heavy rain?"

REQUIRED_VARS = ("HINDSIGHT_BASE_URL", "HINDSIGHT_API_KEY", "HINDSIGHT_BANK_ID")


def http_error(step: str, error: ApiException) -> None:
    print(f"{step} FAILED: HTTP {error.status} {error.reason}")


def main() -> int:
    load_dotenv()

    values = {name: os.getenv(name, "").strip() for name in REQUIRED_VARS}
    missing = [name for name in REQUIRED_VARS if not values[name]]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing))
        print("Copy .env.example to .env and fill in the values locally.")
        return 1

    base_url = values["HINDSIGHT_BASE_URL"]
    api_key = values["HINDSIGHT_API_KEY"]
    bank_id = values["HINDSIGHT_BANK_ID"]

    connection = "FAIL"
    bank = "FAIL"
    retention = "FAIL"
    recall = "FAIL"
    recalled_texts = []

    client = Hindsight(base_url=base_url, api_key=api_key, timeout=120.0)
    try:
        try:
            version = client.get_version()
            print(f"[1/4] Hindsight connection OK (api_version={version.api_version})")
            connection = "PASS"
        except ApiException as error:
            http_error("[1/4] Hindsight connection:", error)
            print("Aborting: without a connection the remaining steps cannot run.")
            print_summary(connection, bank, retention, recall, recalled_texts)
            return 1

        try:
            profile = client.create_bank(bank_id=bank_id, name="KisanMemory")
            print(f"[2/4] Bank ready: {profile.bank_id}")
            bank = "PASS"
        except ApiException as error:
            # create_bank is an upsert; if the server still rejects it, check
            # that the bank already exists so reruns do not fail.
            try:
                client.list_memories(bank_id=bank_id, limit=1)
                print(
                    f"[2/4] Bank '{bank_id}' already exists "
                    f"(create_bank returned HTTP {error.status}); verified with list_memories."
                )
                bank = "PASS"
            except ApiException as probe_error:
                http_error("[2/4] Bank creation/check:", probe_error)

        try:
            response = client.retain(bank_id=bank_id, content=MEMORY)
            print(
                f"[3/4] Memory retained: success={response.success} "
                f"items_count={response.items_count}"
            )
            retention = "PASS"
        except ApiException as error:
            http_error("[3/4] Memory retention:", error)

        try:
            result = client.recall(bank_id=bank_id, query=QUERY)
            if not result.results:
                print("[4/4] No results yet; waiting 5s for indexing...")
                time.sleep(5)
                result = client.recall(bank_id=bank_id, query=QUERY)

            if result.results:
                print(f"[4/4] Recall returned {len(result.results)} result(s):")
                for index, memory in enumerate(result.results, start=1):
                    print(f"  ({index}) type={memory.type}")
                    print(f"      {memory.text}")
                    recalled_texts.append(memory.text)
                recall = "PASS"
            else:
                print("[4/4] Recall returned no results after one retry.")
        except ApiException as error:
            http_error("[4/4] Memory recall:", error)
    finally:
        client.close()

    print_summary(connection, bank, retention, recall, recalled_texts)
    return 0 if "FAIL" not in (connection, bank, retention, recall) else 1


def print_summary(connection, bank, retention, recall, recalled_texts) -> None:
    print("")
    print("========== PHASE 1 RESULTS ==========")
    print(f"Hindsight connection: {connection}")
    print(f"Bank creation/check:  {bank}")
    print(f"Memory retention:     {retention}")
    print(f"Memory recall:        {recall}")
    if recalled_texts:
        print("Recalled memory text:")
        for text in recalled_texts:
            print(f"  - {text}")
    print("=====================================")


if __name__ == "__main__":
    sys.exit(main())
