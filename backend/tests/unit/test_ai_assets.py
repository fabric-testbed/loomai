"""Tests for canonical and legacy AI asset Markdown metadata."""

from pathlib import Path

from app.ai_assets import (
    parse_markdown_asset,
    serialize_markdown_asset,
    validate_markdown_asset,
)


def test_parse_canonical_frontmatter_with_lists():
    content = """---
id: create-weave
name: create-weave
description: Create a weave
domains:
  - weave
  - fablib
tools: [loomai, claude-code]
---

# Body
Instructions.
"""

    parsed = parse_markdown_asset(content)

    assert parsed.style == "frontmatter"
    assert parsed.metadata["id"] == "create-weave"
    assert parsed.metadata["description"] == "Create a weave"
    assert parsed.metadata["domains"] == ["weave", "fablib"]
    assert parsed.metadata["tools"] == ["loomai", "claude-code"]
    assert parsed.body.startswith("# Body")


def test_parse_legacy_frontmatter():
    content = """name: create-slice
description: Create a slice
---
Create a draft topology.
"""

    parsed = parse_markdown_asset(content)

    assert parsed.style == "legacy"
    assert parsed.metadata["name"] == "create-slice"
    assert parsed.metadata["description"] == "Create a slice"
    assert parsed.body == "Create a draft topology."


def test_parse_description_first_legacy_frontmatter():
    content = """description: FABRIC resource manager
---
You manage FABRIC resources.
"""

    parsed = parse_markdown_asset(content)

    assert parsed.style == "legacy"
    assert parsed.metadata["description"] == "FABRIC resource manager"
    assert parsed.body == "You manage FABRIC resources."


def test_serialize_uses_canonical_frontmatter():
    content = serialize_markdown_asset(
        {
            "id": "query-chameleon",
            "name": "query-chameleon",
            "description": "Browse Chameleon resources",
            "domains": ["chameleon", "openstack"],
        },
        "Body",
    )

    assert content.startswith("---\nid: query-chameleon\n")
    assert "domains:\n  - chameleon\n  - openstack\n" in content
    assert content.endswith("---\nBody\n")


def test_validate_canonical_asset_success():
    content = serialize_markdown_asset(
        {
            "id": "benchmark",
            "name": "benchmark",
            "asset_type": "skill",
            "audience": "end-user",
            "description": "Run benchmarks",
            "domains": ["fabric", "testing"],
            "tools": ["loomai", "claude-code"],
        },
        "Benchmark instructions.",
    )

    assert validate_markdown_asset(content, filename_stem="benchmark", require_canonical=True) == []


def test_validate_canonical_asset_reports_errors():
    content = """---
id: Benchmark
name: benchmark
asset_type: workflow
audience: users
description: Bad asset
tools:
  - unknown-tool
---

Body.
"""

    errors = validate_markdown_asset(content, filename_stem="benchmark", require_canonical=True)

    assert "id must use lowercase letters, digits, and hyphens" in errors
    assert "id must match filename stem 'benchmark'" in errors
    assert "invalid asset_type: workflow" in errors
    assert "invalid audience: users" in errors
    assert "invalid tools: unknown-tool" in errors


def test_pilot_skills_are_valid_canonical_assets():
    repo_root = Path(__file__).resolve().parents[3]
    pilot_ids = {
        "benchmark",
        "create-chameleon-lease",
        "create-tutorial",
        "query-chameleon",
    }

    for asset_id in pilot_ids:
        path = repo_root / "ai-tools" / "shared" / "skills" / f"{asset_id}.md"
        errors = validate_markdown_asset(
            path.read_text(),
            filename_stem=asset_id,
            require_canonical=True,
        )
        assert errors == [], f"{path}: {errors}"


def test_backend_mirror_pilot_skills_are_valid_canonical_assets():
    repo_root = Path(__file__).resolve().parents[3]
    pilot_ids = {
        "benchmark",
        "create-chameleon-lease",
        "create-tutorial",
        "query-chameleon",
    }

    for asset_id in pilot_ids:
        path = repo_root / "backend" / "ai-tools" / "shared" / "skills" / f"{asset_id}.md"
        errors = validate_markdown_asset(
            path.read_text(),
            filename_stem=asset_id,
            require_canonical=True,
        )
        assert errors == [], f"{path}: {errors}"


def test_curated_rag_starter_assets_are_valid_canonical_assets():
    repo_root = Path(__file__).resolve().parents[3]
    for base in (repo_root / "ai-tools", repo_root / "backend" / "ai-tools"):
        path = base / "shared" / "corpus" / "curated-rag-starter.md"
        errors = validate_markdown_asset(
            path.read_text(),
            filename_stem="curated-rag-starter",
            require_canonical=True,
        )
        assert errors == [], f"{path}: {errors}"


def test_rag_curated_loader_indexes_all_requested_domains():
    repo_root = Path(__file__).resolve().parents[3]
    from app.rag import load_curated_assets

    chunks = load_curated_assets(str(repo_root / "ai-tools"))

    assert chunks
    assert all(c.source_type == "curated" for c in chunks)
    domains = set(chunks[0].metadata["domains"])
    assert {
        "fabric",
        "fablib",
        "weave",
        "chameleon",
        "openstack",
        "federated",
        "troubleshooting",
        "loomai",
    }.issubset(domains)
    assert "backend/default_artifacts/Hello_FABRIC/weave.json" in chunks[0].metadata["source_paths"]
    assert chunks[0].metadata["freshness"] == "review-on-change"
    assert any("Chameleon And OpenStack Patterns" in c.text for c in chunks)


def test_rag_fablib_examples_have_curated_metadata():
    repo_root = Path(__file__).resolve().parents[3]
    from app.rag import load_fablib_examples

    chunks = load_fablib_examples(str(repo_root / "ai-tools"))
    by_path = {c.source_path: c for c in chunks}

    openstack = by_path["ai-tools/fablib-examples/chameleon/openstack_api_patterns.py"]
    federated = by_path["ai-tools/fablib-examples/experiments/federated_slice_weave_pattern.py"]

    assert openstack.metadata["curated"] is True
    assert {"chameleon", "openstack"}.issubset(set(openstack.metadata["domains"]))
    assert openstack.metadata["source_paths"] == [
        "ai-tools/fablib-examples/chameleon/openstack_api_patterns.py"
    ]
    assert openstack.metadata["freshness"] == "review-on-change"
    assert "federated" in federated.metadata["domains"]


def test_rag_loads_repo_default_weaves_as_curated_starter_examples():
    repo_root = Path(__file__).resolve().parents[3]
    from app.rag import load_default_weaves

    chunks = load_default_weaves(str(repo_root / "ai-tools"))
    by_source = {c.source_path: c for c in chunks}

    hello = by_source["backend/default_artifacts/Hello_FABRIC/weave.json"]
    assert hello.metadata["origin"] == "default"
    assert hello.metadata["curated"] is True
    assert "weave" in hello.metadata["domains"]
    assert "Tool code" in hello.text


def test_rag_status_summarizes_curated_domains(tmp_path):
    from app.rag import Chunk, Embedder, RAGIndex

    class DummyEmbedder(Embedder):
        name = "dummy"
        dims = 1

        def embed_batch(self, texts):
            return [[1.0] for _ in texts]

    idx = RAGIndex(str(tmp_path), DummyEmbedder())
    idx.chunks = [
        Chunk(
            chunk_id="curated:test:0",
            source_type="curated",
            source_path="ai-tools/shared/corpus/test.md",
            section="test",
            text="body",
            file_hash="abc",
            metadata={"curated": True, "domains": ["fabric", "troubleshooting"]},
        )
    ]

    status = idx.status()
    assert status["curated_count"] == 1
    assert status["domains"]["fabric"] == 1
    assert status["domains"]["troubleshooting"] == 1


def test_rag_skill_loader_strips_frontmatter_from_pilot_chunks():
    repo_root = Path(__file__).resolve().parents[3]
    from app.rag import load_skills

    chunks = load_skills(str(repo_root / "ai-tools"))
    benchmark_chunks = [c for c in chunks if c.metadata.get("skill") == "benchmark"]

    assert benchmark_chunks
    assert any("# Benchmarking existing FABRIC slice nodes" in c.text for c in benchmark_chunks)
    assert all("asset_type: skill" not in c.text for c in benchmark_chunks)
    assert all("tools:" not in c.text for c in benchmark_chunks)


def test_ai_agents_crud_parser_reads_canonical_frontmatter():
    repo_root = Path(__file__).resolve().parents[3]
    from app.routes.ai_agents import _parse_md_file

    parsed = _parse_md_file(
        str(repo_root / "ai-tools" / "shared" / "skills" / "benchmark.md")
    )

    assert parsed["name"] == "benchmark"
    assert parsed["description"].startswith("Run ad-hoc network/compute benchmarks")
    assert parsed["body"].startswith("# Benchmarking existing FABRIC slice nodes")
    assert "asset_type: skill" not in parsed["body"]
