"""Item 45.1 -- the one committed writer for the run JSONs under data/eval, and the per-role usage tracker.

The run JSONs that came before this module (`seed44`, `set40`, `afterC2`, `c_control`) were written by ad-hoc code
and recorded no model at all, so the gpt-4o/gpt-4o-mini split could not be read off the artifacts -- nor could the
difference between the 25/27 and 26/27 attribution baselines, which was a prompt-vintage difference, not a judge
difference. This module stamps every record with what produced it.

Roles are separated by a `role:<name>` tag on the call, carried in the call's config. One tracker per run is enough:
`on_chat_model_start` receives the tags, and the tag belongs at the call site, never on a client object --
`agent.py`'s `llm` serves three roles (retrieval agent, composer, reflect), and tags accumulate from parent to
child. The tracker is passed through the run's config, never kept as a module-level accumulator, because
`run_experiment` evaluates with `max_concurrency=2`.

Two recorded fields exist to catch a silent substitution:
- `models_returned` comes from the generation's `response_metadata["model_name"]`, which `langchain_openai` fills
  from the API response's `model` field (base.py:1876); the requested name lives in the configuration block, read
  from the client (base.py:1404 builds the llm_output name from `self.model_name`).
- `cache_read_tokens` matches any `input_token_details` key ending in `cache_read`, because the key is
  service-tier prefixed when a tier exists (`flex_cache_read`, `priority_cache_read`).
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from langchain_core.callbacks import BaseCallbackHandler

from ParallelProse.catalog import DATA_DIR

ROLE_TAG_PREFIX = "role:"
CACHE_READ_SUFFIX = "cache_read"
EVAL_DIR = DATA_DIR / "eval"


def role_of(tags: Iterable[str] | None) -> tuple[str | None, list[str]]:
    """The single role a call carries, plus every role tag seen, so two is visible rather than resolved."""
    seen = sorted({tag[len(ROLE_TAG_PREFIX):] for tag in (tags or []) if tag.startswith(ROLE_TAG_PREFIX)})
    return (seen[0] if len(seen) == 1 else None), seen


def _text(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)


def _message_parts(message: Any) -> list:
    return [getattr(message, "type", "?"), _text(getattr(message, "content", "")),
            json.dumps(getattr(message, "tool_calls", None) or [], ensure_ascii=False, sort_keys=True)]


def prompt_sha(messages: Iterable[Any]) -> str:
    """sha256 over the prompt text, so a prompt change is visible between two records of the same role.
    `on_chat_model_start` hands over a list of message lists (one per prompt in the batch), not a flat list."""
    batches = [[_message_parts(message) for message in (item if isinstance(item, (list, tuple)) else [item])]
               for item in messages]
    return sha256(json.dumps(batches, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def cache_read_tokens(usage: dict | None) -> int:
    """Cache reads under any service tier: the key is `cache_read` or `<tier>_cache_read`."""
    details = (usage or {}).get("input_token_details") or {}
    return sum(int(value or 0) for key, value in details.items() if key.endswith(CACHE_READ_SUFFIX))


class RoleUsageTracker(BaseCallbackHandler):
    """One instance per run; aggregates calls, tokens, cache reads, prompt hashes and returned models by role."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: Counter = Counter()
        self.input_tokens: Counter = Counter()
        self.output_tokens: Counter = Counter()
        self.cache_reads: Counter = Counter()
        self.returned_models: dict[str, Counter] = defaultdict(Counter)
        self.prompt_shas: dict[str, Counter] = defaultdict(Counter)
        self.warnings: list[str] = []
        self._pending: dict[str, tuple[str, str]] = {}

    def _attribute(self, tags: Iterable[str] | None, run_id: Any) -> str:
        role, seen = role_of(tags)
        if role is not None:
            return role
        if seen:  # the spec says raise, not resolve: two role tags mean the accounting would be wrong
            raise ValueError(f"call {run_id}: more than one role tag {seen}; a call carries exactly one")
        self.warnings.append(f"call {run_id}: no role tag; counted as 'unattributed'")
        return "unattributed"

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None,
                            metadata=None, **kwargs):
        role = self._attribute(tags, run_id)
        self._pending[str(run_id)] = (role, prompt_sha(messages))

    def on_llm_end(self, response, *, run_id, parent_run_id=None, tags=None, **kwargs):
        role, prompt = self._pending.pop(str(run_id), (None, ""))
        if role is None:  # an end whose start the tracker never saw: still counted, never silent
            self.warnings.append(f"call {run_id}: on_llm_end without on_chat_model_start; counted as 'unattributed'")
            role = "unattributed"
        self.calls[role] += 1
        if prompt:
            self.prompt_shas[role][prompt] += 1
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) or {}
                self.input_tokens[role] += int(usage.get("input_tokens") or 0)
                self.output_tokens[role] += int(usage.get("output_tokens") or 0)
                self.cache_reads[role] += cache_read_tokens(usage)
                response_metadata = getattr(message, "response_metadata", None) or {}
                returned = response_metadata.get("model_name") or response_metadata.get("model") or "unknown"
                self.returned_models[role][returned] += 1

    def on_llm_error(self, error, *, run_id, parent_run_id=None, tags=None, **kwargs):
        self._pending.pop(str(run_id), None)
        self.warnings.append(f"call {run_id}: {type(error).__name__}")

    def as_dict(self) -> dict[str, Any]:
        roles = sorted(set(self.calls) | set(self.input_tokens) | set(self.output_tokens)
                       | set(self.cache_reads) | set(self.returned_models) | set(self.prompt_shas))
        return {
            "roles": {
                role: {
                    "calls": self.calls.get(role, 0),
                    "input_tokens": self.input_tokens.get(role, 0),
                    "output_tokens": self.output_tokens.get(role, 0),
                    "cache_read_tokens": self.cache_reads.get(role, 0),
                    "models_returned": dict(self.returned_models.get(role, {})),
                    "prompt_shas": dict(self.prompt_shas.get(role, {})),
                }
                for role in roles
            },
            "warnings": list(self.warnings),
        }


def is_peak(when: datetime) -> bool:
    """DeepSeek's peak window: 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday. Chinese holidays are not modelled."""
    if when.weekday() >= 5:
        return False
    return 1 <= when.hour < 4 or 6 <= when.hour < 10


def write_run_record(record: dict, usage: RoleUsageTracker, configuration: dict, *, prefix: str = "run",
                     out_dir: Path = EVAL_DIR, now: datetime | None = None) -> Path:
    """The one committed writer: the record plus what produced it, so no run is model-anonymous again."""
    now = now or datetime.now(timezone.utc)
    payload = {
        **record,
        "meta": {
            "recorded_at": now.isoformat(timespec="seconds"),
            "peak": is_peak(now),
            "configuration": configuration,
            "usage": usage.as_dict(),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prefix}_{now:%Y-%m-%d_%H%M%S}_{record.get('id', 'record')}.json"
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    return path
