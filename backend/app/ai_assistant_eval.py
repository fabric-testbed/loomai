"""Static assistant quality eval assets and checks.

The eval loop is intentionally deterministic: it validates prompt assets,
intent routing, tool-schema filtering, and corpus coverage without making live
LLM calls. Live model probes can build on the same eval assets later.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.ai_assets import parse_markdown_asset


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TOKEN_RE = re.compile(r"[a-z0-9_@.+-]+", re.IGNORECASE)


@dataclass(frozen=True)
class AssistantEvalCase:
    """One canonical assistant eval case loaded from shared/evals."""

    case_id: str
    name: str
    description: str
    prompt: str
    body: str
    metadata: dict[str, Any]
    source_path: str

    @property
    def expected_tools(self) -> list[str]:
        return _metadata_list(self.metadata.get("expected_tools"))

    @property
    def expected_retrieval_domains(self) -> list[str]:
        return _metadata_list(self.metadata.get("expected_retrieval_domains"))

    @property
    def expected_source_types(self) -> list[str]:
        return _metadata_list(self.metadata.get("expected_source_types"))

    @property
    def profile_tiers(self) -> list[str]:
        return _metadata_list(self.metadata.get("profile_tiers")) or ["standard", "large"]

    @property
    def prompt_variants(self) -> list[str]:
        return _metadata_list(self.metadata.get("prompt_variants"))

    @property
    def required_prompt_terms(self) -> list[str]:
        return _metadata_list(self.metadata.get("required_prompt_terms"))

    @property
    def triggers(self) -> list[str]:
        return _metadata_list(self.metadata.get("triggers"))

    @property
    def expected_intent_tool(self) -> str:
        return str(self.metadata.get("expected_intent_tool", "") or "")

    @property
    def expected_intent_confidence(self) -> str:
        return str(self.metadata.get("expected_intent_confidence", "") or "")


def _metadata_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _extract_markdown_section(body: str, heading: str) -> str:
    """Extract a second-level Markdown section body by heading name."""
    matches = list(_SECTION_RE.finditer(body))
    for idx, match in enumerate(matches):
        if match.group(1).strip().lower() != heading.lower():
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        return body[start:end].strip()
    return ""


def load_assistant_eval_cases(ai_tools_dir: str) -> list[AssistantEvalCase]:
    """Load canonical eval assets from ai-tools/shared/evals/*.md."""
    evals_dir = os.path.join(ai_tools_dir, "shared", "evals")
    if not os.path.isdir(evals_dir):
        return []

    cases: list[AssistantEvalCase] = []
    for fname in sorted(os.listdir(evals_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(evals_dir, fname)
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue

        parsed = parse_markdown_asset(text)
        metadata = parsed.metadata
        case_id = str(metadata.get("id") or fname[:-3])
        prompt = _extract_markdown_section(parsed.body, "Prompt")
        cases.append(
            AssistantEvalCase(
                case_id=case_id,
                name=str(metadata.get("name") or case_id),
                description=str(metadata.get("description") or ""),
                prompt=prompt,
                body=parsed.body,
                metadata=metadata,
                source_path=os.path.join("ai-tools", "shared", "evals", fname),
            )
        )
    return cases


def validate_eval_case(case: AssistantEvalCase) -> list[str]:
    """Return structural errors for a loaded eval case."""
    errors: list[str] = []
    if not case.prompt:
        errors.append("missing ## Prompt section")
    if not case.expected_tools and not case.expected_retrieval_domains:
        errors.append("eval should declare expected_tools or expected_retrieval_domains")
    if case.metadata.get("asset_type") != "eval":
        errors.append("asset_type must be eval")
    return errors


def missing_expected_tools(case: AssistantEvalCase, schemas: list[dict]) -> list[str]:
    """Return expected tools that are absent from the full tool schema list."""
    names = {schema.get("function", {}).get("name") for schema in schemas}
    return [tool for tool in case.expected_tools if tool not in names]


def missing_expected_tools_by_tier(case: AssistantEvalCase, schemas: list[dict]) -> dict[str, list[str]]:
    """Return expected tools that are filtered out for each declared model tier."""
    from app.chat_context import PROFILE_TIERS, filter_tool_schemas

    missing: dict[str, list[str]] = {}
    for tier in case.profile_tiers:
        profile = PROFILE_TIERS[tier]
        filtered = filter_tool_schemas(schemas, profile["max_tools"])
        names = {schema.get("function", {}).get("name") for schema in filtered}
        missing[tier] = [tool for tool in case.expected_tools if tool not in names]
    return missing


def prompt_text_for_variant(variant: str) -> str:
    """Return the system prompt text used for static prompt-regression checks."""
    if variant == "loomai-compact":
        from app.chat_prompt import LOOMAI_MODE_PROMPT

        return LOOMAI_MODE_PROMPT
    if variant == "loomai-extended":
        from app.chat_prompt import LOOMAI_MODE_EXTENDED

        return LOOMAI_MODE_EXTENDED

    from app.chat_context import get_system_prompt

    return get_system_prompt(variant)


def missing_prompt_terms(case: AssistantEvalCase) -> dict[str, list[str]]:
    """Return required prompt terms missing from each declared prompt variant."""
    missing: dict[str, list[str]] = {}
    for variant in case.prompt_variants:
        prompt_text = prompt_text_for_variant(variant)
        lower = prompt_text.lower()
        missing[variant] = [
            term for term in case.required_prompt_terms
            if term.lower() not in lower
        ]
    return missing


def intent_mismatch(case: AssistantEvalCase) -> dict[str, str] | None:
    """Return intent mismatch details for cases that declare intent expectations."""
    if not case.expected_intent_tool and not case.expected_intent_confidence:
        return None

    from app.chat_intent import detect_intent

    tool, _args, confidence = detect_intent(case.prompt)
    errors: dict[str, str] = {}
    if case.expected_intent_tool and tool != case.expected_intent_tool:
        errors["tool"] = f"expected {case.expected_intent_tool}, got {tool}"
    if case.expected_intent_confidence and confidence != case.expected_intent_confidence:
        errors["confidence"] = f"expected {case.expected_intent_confidence}, got {confidence}"
    return errors or None


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def lexical_retrieval_hits(
    case: AssistantEvalCase,
    chunks: Iterable[Any],
    *,
    k: int = 12,
) -> list[Any]:
    """Rank corpus chunks with a deterministic lexical proxy for retrieval."""
    query_tokens = _tokens(" ".join([case.prompt, *case.triggers]))
    if not query_tokens:
        return []

    scored: list[tuple[float, Any]] = []
    for chunk in chunks:
        metadata = getattr(chunk, "metadata", {}) or {}
        domains = set(_metadata_list(metadata.get("domains")))
        source_type = str(getattr(chunk, "source_type", ""))
        searchable = " ".join(
            [
                str(getattr(chunk, "section", "")),
                str(getattr(chunk, "source_path", "")),
                str(getattr(chunk, "text", "")),
                " ".join(domains),
            ]
        )
        overlap = len(query_tokens & _tokens(searchable))
        domain_bonus = 2 * len(domains & set(case.expected_retrieval_domains))
        source_bonus = 6 if source_type in set(case.expected_source_types) else 0
        score = overlap + domain_bonus + source_bonus
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda item: (-item[0], getattr(item[1], "source_path", "")))
    return [chunk for _score, chunk in scored[:k]]


def retrieval_expectation_gaps(
    case: AssistantEvalCase,
    chunks: Iterable[Any],
    *,
    k: int = 12,
) -> dict[str, list[str]]:
    """Check whether top lexical hits cover expected domains and source types."""
    hits = lexical_retrieval_hits(case, chunks, k=k)
    seen_domains: set[str] = set()
    seen_source_types: set[str] = set()
    for chunk in hits:
        seen_source_types.add(str(getattr(chunk, "source_type", "")))
        metadata = getattr(chunk, "metadata", {}) or {}
        seen_domains.update(_metadata_list(metadata.get("domains")))

    return {
        "domains": [
            domain for domain in case.expected_retrieval_domains
            if domain not in seen_domains
        ],
        "source_types": [
            source_type for source_type in case.expected_source_types
            if source_type not in seen_source_types
        ],
    }
