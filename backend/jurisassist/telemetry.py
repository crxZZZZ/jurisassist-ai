import json
import logging

from prometheus_client import Counter, Histogram

requests = Counter("juris_http_requests_total", "HTTP requests", ["method", "route", "status"])
latency = Histogram("juris_http_duration_seconds", "HTTP duration", ["route"])
jobs = Counter("juris_jobs_total", "Completed job attempts", ["kind", "status"])
tools = Counter("juris_tool_calls_total", "Allowed tool calls", ["tool"])
retrieval = Histogram("juris_retrieval_seconds", "Retrieval duration", ["mode"])
llm = Histogram("juris_llm_seconds", "Model latency")
tokens = Counter("juris_model_tokens_total", "Model token count", ["direction"])


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"level": record.levelname, "event": record.getMessage(), "logger": record.name}
        for key in ("request_id", "job_id", "kind", "error_type", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level="INFO"):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # Never log HTTP URLs that may contain user queries, or exception payloads.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
