"""Tests for the static LoomAI assistant quality eval loop."""

from pathlib import Path

from app.ai_assets import validate_markdown_asset
from app.ai_assistant_eval import (
    intent_mismatch,
    load_assistant_eval_cases,
    missing_expected_tools,
    missing_expected_tools_by_tier,
    missing_prompt_terms,
    retrieval_expectation_gaps,
    validate_eval_case,
)
from app.rag import (
    load_curated_assets,
    load_fabric_ai_md,
    load_fablib_examples,
    load_default_weaves,
    load_skills,
)
from app.routes.ai_chat import TOOL_SCHEMAS


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _quality_corpus(ai_tools_dir: Path):
    chunks = []
    chunks.extend(load_fabric_ai_md(str(ai_tools_dir)))
    chunks.extend(load_curated_assets(str(ai_tools_dir)))
    chunks.extend(load_skills(str(ai_tools_dir)))
    chunks.extend(load_fablib_examples(str(ai_tools_dir)))
    chunks.extend(load_default_weaves(str(ai_tools_dir)))
    return chunks


def test_assistant_eval_assets_are_valid_canonical_markdown():
    repo_root = _repo_root()
    for base in (repo_root / "ai-tools", repo_root / "backend" / "ai-tools"):
        evals_dir = base / "shared" / "evals"
        paths = sorted(evals_dir.glob("*.md"))
        assert len(paths) >= 5
        for path in paths:
            errors = validate_markdown_asset(
                path.read_text(),
                filename_stem=path.stem,
                require_canonical=True,
            )
            assert errors == [], f"{path}: {errors}"


def test_assistant_eval_loader_reads_cases_and_prompts():
    cases = load_assistant_eval_cases(str(_repo_root() / "ai-tools"))

    assert {case.case_id for case in cases} >= {
        "create-weave-fablib-code",
        "write-fablib-network-code",
        "extend-chameleon-slice",
        "debug-federated-topology",
        "explain-stableerror-ssh",
    }
    for case in cases:
        assert validate_eval_case(case) == []
        assert case.prompt


def test_assistant_eval_expected_tools_exist_in_schema():
    cases = load_assistant_eval_cases(str(_repo_root() / "ai-tools"))

    for case in cases:
        missing = missing_expected_tools(case, TOOL_SCHEMAS)
        assert missing == [], f"{case.case_id}: missing full-schema tools {missing}"


def test_assistant_eval_expected_tools_survive_model_tier_filtering():
    cases = load_assistant_eval_cases(str(_repo_root() / "ai-tools"))

    for case in cases:
        missing_by_tier = missing_expected_tools_by_tier(case, TOOL_SCHEMAS)
        missing_by_tier = {
            tier: missing for tier, missing in missing_by_tier.items() if missing
        }
        assert missing_by_tier == {}, f"{case.case_id}: filtered out {missing_by_tier}"


def test_assistant_eval_intent_expectations_match_router():
    cases = load_assistant_eval_cases(str(_repo_root() / "ai-tools"))

    for case in cases:
        mismatch = intent_mismatch(case)
        assert mismatch is None, f"{case.case_id}: {mismatch}"


def test_assistant_eval_prompt_regression_terms_are_present():
    cases = load_assistant_eval_cases(str(_repo_root() / "ai-tools"))

    for case in cases:
        missing_by_variant = missing_prompt_terms(case)
        missing_by_variant = {
            variant: missing for variant, missing in missing_by_variant.items() if missing
        }
        assert missing_by_variant == {}, f"{case.case_id}: {missing_by_variant}"


def test_assistant_eval_retrieval_expectations_have_corpus_coverage():
    repo_root = _repo_root()
    ai_tools_dir = repo_root / "ai-tools"
    cases = load_assistant_eval_cases(str(ai_tools_dir))
    chunks = _quality_corpus(ai_tools_dir)

    assert chunks
    for case in cases:
        gaps = retrieval_expectation_gaps(case, chunks)
        gaps = {kind: missing for kind, missing in gaps.items() if missing}
        assert gaps == {}, f"{case.case_id}: retrieval gaps {gaps}"
