"""Small, explicit sample comparing real prompts. Not a full quality benchmark."""

import json
import time
from pathlib import Path

from jurisassist import telemetry
from jurisassist.ai import research_chat
from jurisassist.config import get_settings
from jurisassist.db import session_factory
from jurisassist.evaluation import load_cases


def tool_count():
    return sum(
        s.value
        for metric in telemetry.tools.collect()
        for s in metric.samples
        if s.name.endswith("_total")
    )


def main():
    if not get_settings().database_url.endswith("/jurisassist_benchmark"):
        raise SystemExit("Use exclusivamente jurisassist_benchmark.")
    results = []
    Path("reports").mkdir(exist_ok=True)
    output = Path("reports/model-chat-comparison.json")
    cases = {case["id"]: case for case in load_cases()}
    with session_factory()() as db:
        for version in ["v1", "v2"]:
            for key in ["L01", "L25", "U02", "A06"]:
                print(f"Executando {key} / {version}", flush=True)
                started, before = time.perf_counter(), tool_count()
                result = research_chat(db, "benchmark", cases[key]["question"], version=version)
                entry = {
                    "id": key,
                    "prompt_version": version,
                    "seconds": round(time.perf_counter() - started, 2),
                    "tool_calls": tool_count() - before,
                    "answer": result,
                }
                results.append(entry)
                output.write_text(
                    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps({k: v for k, v in entry.items() if k != "answer"}), flush=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
