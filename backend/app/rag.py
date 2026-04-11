"""Retrieval-Augmented Generation for the LoomAI assistant.

The RAG layer indexes the project knowledge corpus — FABRIC_AI.md, agent
personas, skills, FABlib examples, weaves/artifacts, and the site/component
catalog — into a lightweight on-disk vector store and exposes top-K semantic
retrieval for the chat handler.

Design highlights
-----------------
- **Universal embedder**: default is local ``fastembed`` (BAAI/bge-small-en-v1.5,
  384-dim, ONNX runtime). At startup we also probe each configured LLM provider
  for ``/v1/embeddings`` support; if a remote embedder is available we prefer
  it for higher-quality vectors.
- **Hybrid retrieval**: cosine similarity against the semantic index plus a
  BM25 keyword score as a safety-net for exact-term queries (weave names,
  tool names, site IDs). Final score is a weighted sum.
- **Incremental refresh**: every source file's sha256 is stored with its
  chunks. On each chat request we cheaply walk the corpus directories, hash
  small files, and re-embed only changed chunks.
- **Storage**: one directory per index under ``{storage}/.loomai/rag_index/``
  with ``vectors.npy`` (float32 matrix) and ``metadata.json``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (singleton)
# ---------------------------------------------------------------------------

_INDEX: Optional["RAGIndex"] = None
_INDEX_LOCK = asyncio.Lock()
_INDEX_VERSION = 2  # bump when on-disk schema changes

# Default local embedding model (small, fast, well-studied)
_DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
_DEFAULT_LOCAL_DIMS = 384

# Candidate embedding model names to probe on each provider (in order). The
# first one the provider accepts becomes that provider's embedder identity.
_REMOTE_EMBED_CANDIDATES = [
    "qwen3-embedding",
    "text-embedding-3-small",
    "text-embedding-ada-002",
    "bge-small-en-v1.5",
    "nomic-embed-text",
]


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """A single retrievable passage."""

    chunk_id: str              # unique id, usually "{source_type}:{source_path}:{idx}"
    source_type: str           # "fabric_ai" | "skill" | "agent" | "example" | "weave" | "site"
    source_path: str           # relative path within corpus
    section: str               # section title / H-path / tag
    text: str                  # the passage body
    file_hash: str             # sha256 of the source file (for incremental refresh)
    metadata: dict = field(default_factory=dict)  # extra (tags, weave name, etc.)


# ---------------------------------------------------------------------------
# Corpus loaders — each returns a list of Chunk
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
    except OSError:
        return ""
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _split_markdown_by_heading(
    text: str,
    *,
    max_chars: int = 2000,
    min_chars: int = 200,
) -> list[tuple[str, str]]:
    """Split markdown into (section_path, body) chunks on H2/H3 boundaries.

    Headings deeper than H3 stay inside their parent chunk. Very long
    sections get further split on blank-line boundaries to keep chunks
    roughly ``max_chars`` long. Very short adjacent sections are merged.
    """
    lines = text.splitlines()
    sections: list[tuple[list[str], list[str]]] = []  # (heading_stack, body_lines)
    heading_stack: list[str] = []

    def _flush(body_lines: list[str]) -> None:
        if not body_lines:
            return
        body = "\n".join(body_lines).strip()
        if body:
            sections.append((list(heading_stack), [body]))

    body_lines: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m and len(m.group(1)) <= 3:
            _flush(body_lines)
            body_lines = []
            depth = len(m.group(1))
            title = m.group(2).strip()
            heading_stack = heading_stack[: depth - 1]
            while len(heading_stack) < depth - 1:
                heading_stack.append("")
            heading_stack.append(title)
            continue
        body_lines.append(line)
    _flush(body_lines)

    # Merge tiny sections, split oversized ones
    chunks: list[tuple[str, str]] = []
    buffer_path = ""
    buffer_body = ""
    for path, bodies in sections:
        section_path = " > ".join(p for p in path if p) or "(preface)"
        body = "\n".join(bodies).strip()
        if not body:
            continue
        if len(body) > max_chars:
            # Split on blank lines
            paragraphs = re.split(r"\n\s*\n", body)
            acc = ""
            for p in paragraphs:
                if len(acc) + len(p) + 2 > max_chars and acc:
                    chunks.append((section_path, acc.strip()))
                    acc = p
                else:
                    acc = f"{acc}\n\n{p}" if acc else p
            if acc.strip():
                chunks.append((section_path, acc.strip()))
        elif len(body) < min_chars and buffer_body and buffer_path == section_path:
            buffer_body += "\n\n" + body
        else:
            if buffer_body:
                chunks.append((buffer_path, buffer_body.strip()))
            buffer_path = section_path
            buffer_body = body
    if buffer_body:
        chunks.append((buffer_path, buffer_body.strip()))

    return chunks


def load_fabric_ai_md(ai_tools_dir: str) -> list[Chunk]:
    """Load FABRIC_AI.md as section-level chunks."""
    path = os.path.join(ai_tools_dir, "shared", "FABRIC_AI.md")
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return []
    file_hash = _sha256_text(text)
    chunks = []
    for i, (section, body) in enumerate(_split_markdown_by_heading(text)):
        chunks.append(
            Chunk(
                chunk_id=f"fabric_ai:FABRIC_AI.md:{i}",
                source_type="fabric_ai",
                source_path="ai-tools/shared/FABRIC_AI.md",
                section=section,
                text=f"# FABRIC_AI.md — {section}\n\n{body}",
                file_hash=file_hash,
            )
        )
    return chunks


def load_skills(ai_tools_dir: str) -> list[Chunk]:
    """Load each ai-tools/shared/skills/*.md as one or more chunks."""
    skills_dir = os.path.join(ai_tools_dir, "shared", "skills")
    if not os.path.isdir(skills_dir):
        return []
    chunks = []
    for name in sorted(os.listdir(skills_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(skills_dir, name)
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        # Strip YAML frontmatter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                text = text[end + 3:].lstrip()
        file_hash = _sha256_text(text)
        skill_name = name[:-3]
        for i, (section, body) in enumerate(_split_markdown_by_heading(text, max_chars=1500)):
            chunks.append(
                Chunk(
                    chunk_id=f"skill:{skill_name}:{i}",
                    source_type="skill",
                    source_path=f"ai-tools/shared/skills/{name}",
                    section=f"{skill_name} > {section}",
                    text=f"# Skill: {skill_name}\n## {section}\n\n{body}",
                    file_hash=file_hash,
                    metadata={"skill": skill_name},
                )
            )
    return chunks


def load_agents(ai_tools_dir: str) -> list[Chunk]:
    """Load each ai-tools/shared/agents/*.md as a single chunk per agent."""
    agents_dir = os.path.join(ai_tools_dir, "shared", "agents")
    if not os.path.isdir(agents_dir):
        return []
    chunks = []
    for name in sorted(os.listdir(agents_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(agents_dir, name)
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        file_hash = _sha256_text(text)
        agent_name = name[:-3]
        # Parse frontmatter for description
        description = ""
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                fm = text[3:end]
                body = text[end + 3:].lstrip()
                for line in fm.splitlines():
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                        break
            else:
                body = text
        else:
            body = text
        # One chunk per agent; long agents get multiple
        for i, (section, part) in enumerate(_split_markdown_by_heading(body, max_chars=1800)):
            chunks.append(
                Chunk(
                    chunk_id=f"agent:{agent_name}:{i}",
                    source_type="agent",
                    source_path=f"ai-tools/shared/agents/{name}",
                    section=f"{agent_name}: {description}" if i == 0 else f"{agent_name} > {section}",
                    text=f"# Agent persona: {agent_name}\n{description}\n\n{part}",
                    file_hash=file_hash,
                    metadata={"agent": agent_name, "description": description},
                )
            )
    return chunks


def load_fablib_examples(ai_tools_dir: str) -> list[Chunk]:
    """Load each FABlib example as a single chunk with title + tags + description + code."""
    examples_dir = os.path.join(ai_tools_dir, "fablib-examples")
    index_path = os.path.join(examples_dir, "INDEX.json")
    if not os.path.isfile(index_path):
        return []
    try:
        with open(index_path) as f:
            index = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(index, list):
        return []

    index_hash = _sha256_file(index_path)
    chunks = []
    for entry in index:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title", "")
        rel_file = entry.get("file", "")
        tags = entry.get("tags", []) or []
        description = entry.get("description", "")
        example_path = os.path.join(examples_dir, rel_file) if rel_file else ""
        code_snippet = ""
        file_hash = index_hash
        if example_path and os.path.isfile(example_path):
            try:
                with open(example_path) as f:
                    code_snippet = f.read()
                file_hash = _sha256_text(code_snippet + index_hash)
            except OSError:
                pass
        # Cap code to keep chunks manageable
        if len(code_snippet) > 2500:
            code_snippet = code_snippet[:2500] + "\n# ... (truncated)"
        body = (
            f"# FABlib Example: {title}\n"
            f"**Tags**: {', '.join(tags)}\n"
            f"**File**: `ai-tools/fablib-examples/{rel_file}`\n\n"
            f"{description}\n\n"
            f"```python\n{code_snippet}\n```"
        )
        chunks.append(
            Chunk(
                chunk_id=f"example:{rel_file}",
                source_type="example",
                source_path=f"ai-tools/fablib-examples/{rel_file}",
                section=title,
                text=body,
                file_hash=file_hash,
                metadata={"tags": tags, "title": title, "file": rel_file},
            )
        )
    return chunks


def load_weaves(storage_dirs: Iterable[str]) -> list[Chunk]:
    """Load every weave.json under the given storage directories as a chunk.

    Indexes each weave's name, description, node topology, and any
    ``weave.md`` body (the user-authored description).
    """
    chunks = []
    seen_paths: set[str] = set()
    for storage_dir in storage_dirs:
        if not storage_dir or not os.path.isdir(storage_dir):
            continue
        # Walk my_artifacts/ directories
        for root, dirs, files in os.walk(storage_dir):
            # Skip hidden dot-dirs and caches
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules")]
            if "weave.json" not in files:
                continue
            weave_json = os.path.join(root, "weave.json")
            if weave_json in seen_paths:
                continue
            seen_paths.add(weave_json)
            try:
                with open(weave_json) as f:
                    weave = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(weave, dict):
                continue
            dir_name = os.path.basename(root)
            name = weave.get("name", dir_name)
            description = weave.get("description", "")
            nodes = weave.get("nodes", []) or []
            networks = weave.get("networks", []) or []
            args = weave.get("args", []) or []
            run_script = weave.get("run_script", "")

            # Compose node topology summary
            node_summary = []
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                nname = n.get("name", "?")
                site = n.get("site", "auto")
                cores = n.get("cores", "?")
                ram = n.get("ram", "?")
                image = n.get("image", "")
                comps = n.get("components", []) or []
                comp_str = ", ".join(c.get("model", c.get("type", "?")) for c in comps if isinstance(c, dict))
                node_summary.append(
                    f"- {nname}: site={site} {cores}c/{ram}G image={image}"
                    + (f" components=[{comp_str}]" if comp_str else "")
                )
            net_summary = [
                f"- {n.get('name', '?')} (type={n.get('type', '?')})"
                for n in networks
                if isinstance(n, dict)
            ]
            args_summary = [f"- {a.get('name', '?')}" for a in args if isinstance(a, dict)]

            # Look for a user-authored weave.md in the same directory
            weave_md_path = os.path.join(root, "weave.md")
            weave_md = ""
            if os.path.isfile(weave_md_path):
                try:
                    with open(weave_md_path) as f:
                        weave_md = f.read()[:3000]
                except OSError:
                    pass

            body_parts = [
                f"# Weave: {name}",
                f"**Directory**: `{dir_name}/`",
                f"**Description**: {description}" if description else "",
                f"**Run script**: `{run_script}`" if run_script else "",
                f"**Nodes** ({len(nodes)}):\n" + ("\n".join(node_summary) if node_summary else "(none)"),
                f"**Networks** ({len(networks)}):\n" + ("\n".join(net_summary) if net_summary else "(none)"),
            ]
            if args_summary:
                body_parts.append("**Args**:\n" + "\n".join(args_summary))
            if weave_md:
                body_parts.append("**weave.md**:\n" + weave_md)
            body = "\n\n".join(p for p in body_parts if p)

            file_hash = _sha256_file(weave_json)
            if weave_md:
                file_hash = _sha256_text(file_hash + _sha256_file(weave_md_path))

            rel_path = os.path.relpath(weave_json, storage_dir)
            chunks.append(
                Chunk(
                    chunk_id=f"weave:{dir_name}",
                    source_type="weave",
                    source_path=rel_path,
                    section=name,
                    text=body,
                    file_hash=file_hash,
                    metadata={
                        "weave_name": name,
                        "dir_name": dir_name,
                        "node_count": len(nodes),
                        "has_gpu": any(
                            any("GPU" in c.get("model", "") for c in (n.get("components", []) or []) if isinstance(c, dict))
                            for n in nodes if isinstance(n, dict)
                        ),
                    },
                )
            )
    return chunks


def load_site_catalog() -> list[Chunk]:
    """Produce one chunk per FABRIC site from the hardcoded coordinate table.

    Runs a lightweight FABlib-free snapshot so the index doesn't block on
    a live resource fetch. Full dynamic availability is still accessed via
    the ``query_sites`` tool during chat.
    """
    try:
        from app.routes.resources import _SITE_COORDS
    except Exception:
        return []
    chunks = []
    for site_name, (lat, lon) in _SITE_COORDS.items():
        body = (
            f"# FABRIC Site: {site_name}\n"
            f"Location: ({lat}, {lon})\n"
            f"To check live resource availability (cores, RAM, GPUs, NICs), use the "
            f"`query_sites` tool or `loomai sites {site_name.lower()}` on the CLI."
        )
        chunks.append(
            Chunk(
                chunk_id=f"site:{site_name}",
                source_type="site",
                source_path=f"fabric://sites/{site_name}",
                section=site_name,
                text=body,
                file_hash=_sha256_text(body),
                metadata={"site": site_name, "lat": lat, "lon": lon},
            )
        )
    return chunks


# ---------------------------------------------------------------------------
# Embedder abstraction
# ---------------------------------------------------------------------------


class Embedder:
    """Abstract embedder interface."""

    name: str = "none"
    dims: int = 0

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalFastEmbedder(Embedder):
    """Local ONNX embedder via fastembed (BAAI/bge-small-en-v1.5)."""

    def __init__(self, model: str = _DEFAULT_LOCAL_MODEL, cache_dir: Optional[str] = None) -> None:
        from fastembed import TextEmbedding  # deferred import — heavy

        self.name = f"local:{model}"
        self.dims = _DEFAULT_LOCAL_DIMS
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # fastembed returns a generator of numpy arrays
        return [v.tolist() for v in self._model.embed(texts)]


class RemoteEmbedder(Embedder):
    """OpenAI-compatible remote embedder via httpx."""

    def __init__(self, base_url: str, api_key: str, model: str, dims: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dims = dims
        self.name = f"remote:{model}@{base_url}"

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import httpx

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.base_url}/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": texts},
            )
        resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in data["data"]]


def _probe_remote_embedder() -> Optional[RemoteEmbedder]:
    """Try each configured provider for a working embeddings endpoint.

    Returns a RemoteEmbedder instance on the first success, or None if
    no remote provider supports embeddings with the current keys.
    """
    try:
        from app.settings_manager import load_settings
    except Exception:
        return None

    try:
        settings = load_settings()
    except Exception:
        return None
    ai = settings.get("ai", {}) or {}

    # (base_url, api_key) pairs to probe
    providers: list[tuple[str, str, str]] = []
    fabric_key = ai.get("fabric_api_key") or ""
    if fabric_key:
        providers.append(("fabric", ai.get("ai_server_url", "https://ai.fabric-testbed.net"), fabric_key))
    nrp_key = ai.get("nrp_api_key") or ""
    if nrp_key:
        providers.append(("nrp", ai.get("nrp_server_url", "https://ellm.nrp-nautilus.io"), nrp_key))
    for p in ai.get("custom_providers", []) or []:
        if not isinstance(p, dict):
            continue
        if p.get("api_key") and p.get("base_url"):
            providers.append((f"custom:{p.get('name', '?')}", p["base_url"], p["api_key"]))

    import httpx

    for label, base_url, api_key in providers:
        base = base_url.rstrip("/")
        for candidate in _REMOTE_EMBED_CANDIDATES:
            try:
                with httpx.Client(timeout=15.0) as client:
                    r = client.post(
                        f"{base}/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"model": candidate, "input": "probe"},
                    )
            except Exception as e:
                logger.debug("RAG embed probe %s/%s failed: %s", label, candidate, e)
                continue
            if r.status_code == 200:
                try:
                    d = r.json()
                    dims = len(d["data"][0]["embedding"])
                except Exception:
                    continue
                logger.info(
                    "RAG embed probe: %s on %s → OK (%d dims)", candidate, label, dims
                )
                return RemoteEmbedder(base_url=base, api_key=api_key, model=candidate, dims=dims)
            else:
                logger.debug(
                    "RAG embed probe: %s on %s → %d", candidate, label, r.status_code
                )
    return None


def build_embedder(*, prefer_remote: bool = True, cache_dir: Optional[str] = None) -> Embedder:
    """Build the best available embedder.

    Strategy:
      1. If ``prefer_remote``, probe each configured LLM provider for a
         working ``/v1/embeddings`` endpoint. Use the first one that works.
      2. Else fall back to local fastembed (lazy-downloads model on first use).
    """
    if prefer_remote:
        remote = _probe_remote_embedder()
        if remote is not None:
            return remote
    logger.info("RAG: using local fastembed embedder (%s)", _DEFAULT_LOCAL_MODEL)
    return LocalFastEmbedder(cache_dir=cache_dir)


# ---------------------------------------------------------------------------
# RAG index
# ---------------------------------------------------------------------------


@dataclass
class RetrievalHit:
    chunk: Chunk
    score: float
    semantic_score: float
    bm25_score: float


class RAGIndex:
    """On-disk vector store with hybrid semantic+BM25 retrieval."""

    def __init__(self, index_dir: str, embedder: Embedder) -> None:
        self.index_dir = index_dir
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vectors = None  # numpy.ndarray | None
        self._bm25 = None    # rank_bm25.BM25Okapi | None
        self.last_built: float = 0.0
        self.last_refreshed: float = 0.0
        os.makedirs(self.index_dir, exist_ok=True)

    # --- Persistence -------------------------------------------------------

    @property
    def vectors_path(self) -> str:
        return os.path.join(self.index_dir, "vectors.npy")

    @property
    def metadata_path(self) -> str:
        return os.path.join(self.index_dir, "metadata.json")

    def save(self) -> None:
        import numpy as np

        if self.vectors is not None:
            np.save(self.vectors_path, self.vectors)
        meta = {
            "version": _INDEX_VERSION,
            "embedder": self.embedder.name,
            "dims": self.embedder.dims,
            "chunk_count": len(self.chunks),
            "last_built": self.last_built,
            "last_refreshed": self.last_refreshed,
            "chunks": [asdict(c) for c in self.chunks],
        }
        tmp = self.metadata_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(meta, f)
        os.replace(tmp, self.metadata_path)

    def load(self) -> bool:
        """Load an existing on-disk index. Returns True on success."""
        import numpy as np

        if not (os.path.isfile(self.vectors_path) and os.path.isfile(self.metadata_path)):
            return False
        try:
            with open(self.metadata_path) as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        if meta.get("version") != _INDEX_VERSION:
            logger.info("RAG: on-disk index version mismatch, rebuilding")
            return False
        if meta.get("embedder") != self.embedder.name:
            logger.info(
                "RAG: embedder changed (%s → %s), rebuilding",
                meta.get("embedder"), self.embedder.name,
            )
            return False
        try:
            self.vectors = np.load(self.vectors_path)
        except Exception as e:
            logger.warning("RAG: failed to load vectors.npy: %s", e)
            return False
        self.chunks = [Chunk(**c) for c in meta.get("chunks", [])]
        if self.vectors.shape[0] != len(self.chunks):
            logger.warning("RAG: vector/chunk count mismatch, rebuilding")
            return False
        self.last_built = meta.get("last_built", 0.0)
        self.last_refreshed = meta.get("last_refreshed", 0.0)
        self._bm25 = None  # rebuild lazily
        logger.info(
            "RAG: loaded %d chunks from %s (embedder=%s)",
            len(self.chunks), self.index_dir, self.embedder.name,
        )
        return True

    # --- Building ----------------------------------------------------------

    def _embed_all(self, chunks: list[Chunk], batch_size: int = 32):
        import numpy as np

        if not chunks:
            return np.zeros((0, self.embedder.dims), dtype=np.float32)
        vectors: list[list[float]] = []
        for i in range(0, len(chunks), batch_size):
            batch = [c.text for c in chunks[i : i + batch_size]]
            t0 = time.time()
            embs = self.embedder.embed_batch(batch)
            logger.debug(
                "RAG: embedded batch %d/%d (%d texts, %.2fs)",
                i + len(batch), len(chunks), len(batch), time.time() - t0,
            )
            vectors.extend(embs)
        arr = np.asarray(vectors, dtype=np.float32)
        # L2-normalize so cosine == dot product
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        arr = arr / norms
        return arr

    def build(self, chunks: list[Chunk]) -> None:
        """Full rebuild: embed every chunk and persist."""
        t0 = time.time()
        self.chunks = chunks
        self.vectors = self._embed_all(chunks)
        self._bm25 = None
        self.last_built = time.time()
        self.last_refreshed = self.last_built
        self.save()
        logger.info(
            "RAG: built index with %d chunks in %.1fs (embedder=%s)",
            len(chunks), time.time() - t0, self.embedder.name,
        )

    def incremental_refresh(self, fresh_chunks: list[Chunk]) -> int:
        """Merge fresh_chunks into the existing index.

        - Chunks with unchanged (chunk_id, file_hash) are kept as-is.
        - Chunks with changed file_hash are re-embedded.
        - Chunks present on disk but missing in fresh_chunks are removed.
        Returns the number of re-embedded chunks.
        """
        import numpy as np

        if self.vectors is None or not self.chunks:
            # No existing index — full build
            self.build(fresh_chunks)
            return len(fresh_chunks)

        old_by_id = {c.chunk_id: (i, c) for i, c in enumerate(self.chunks)}
        new_chunks: list[Chunk] = []
        new_vectors: list = []
        to_embed_chunks: list[Chunk] = []
        to_embed_positions: list[int] = []

        for c in fresh_chunks:
            pos = len(new_chunks)
            old_entry = old_by_id.get(c.chunk_id)
            if old_entry is not None and old_entry[1].file_hash == c.file_hash:
                # Reuse old vector
                old_idx, old_chunk = old_entry
                new_chunks.append(old_chunk)
                new_vectors.append(self.vectors[old_idx])
            else:
                new_chunks.append(c)
                new_vectors.append(None)  # placeholder
                to_embed_chunks.append(c)
                to_embed_positions.append(pos)

        if to_embed_chunks:
            embedded = self._embed_all(to_embed_chunks)
            for pos, vec in zip(to_embed_positions, embedded):
                new_vectors[pos] = vec

        self.chunks = new_chunks
        self.vectors = np.asarray(
            [v if v is not None else np.zeros(self.embedder.dims, dtype=np.float32) for v in new_vectors],
            dtype=np.float32,
        )
        self._bm25 = None
        self.last_refreshed = time.time()
        if not self.last_built:
            self.last_built = self.last_refreshed
        self.save()
        logger.info(
            "RAG: incremental refresh — %d re-embedded, %d total chunks",
            len(to_embed_chunks), len(new_chunks),
        )
        return len(to_embed_chunks)

    # --- Retrieval ---------------------------------------------------------

    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("RAG: rank_bm25 not installed, BM25 disabled")
            self._bm25 = False  # type: ignore
            return
        corpus = [re.findall(r"\w+", c.text.lower()) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else False  # type: ignore

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        semantic_weight: float = 0.7,
        bm25_weight: float = 0.3,
        min_score: float = 0.25,
        source_type_filter: Optional[set[str]] = None,
    ) -> list[RetrievalHit]:
        """Retrieve the top-K chunks for a query with hybrid scoring."""
        import numpy as np

        if self.vectors is None or not self.chunks:
            return []
        query = (query or "").strip()
        if not query:
            return []

        # Semantic score
        try:
            q_emb = self.embedder.embed_batch([query])[0]
            q_vec = np.asarray(q_emb, dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 0:
                q_vec = q_vec / q_norm
            sem_scores = self.vectors @ q_vec  # cosine because everything is unit
        except Exception as e:
            logger.warning("RAG: semantic embed failed: %s — falling back to BM25 only", e)
            sem_scores = np.zeros(len(self.chunks), dtype=np.float32)
            semantic_weight = 0.0
            bm25_weight = 1.0

        # BM25 score
        self._ensure_bm25()
        if self._bm25 and self._bm25 is not False:
            tokens = re.findall(r"\w+", query.lower())
            try:
                bm25_raw = np.asarray(self._bm25.get_scores(tokens), dtype=np.float32)
                bm25_max = float(bm25_raw.max()) if bm25_raw.size else 0.0
                bm25_scores = bm25_raw / bm25_max if bm25_max > 0 else bm25_raw
            except Exception as e:
                logger.debug("RAG: BM25 scoring failed: %s", e)
                bm25_scores = np.zeros(len(self.chunks), dtype=np.float32)
        else:
            bm25_scores = np.zeros(len(self.chunks), dtype=np.float32)

        combined = semantic_weight * sem_scores + bm25_weight * bm25_scores

        # Apply source_type filter as a mask
        if source_type_filter:
            for i, c in enumerate(self.chunks):
                if c.source_type not in source_type_filter:
                    combined[i] = -1.0

        top_idx = np.argsort(-combined)[: k * 2]  # over-fetch then filter by min_score
        hits: list[RetrievalHit] = []
        for i in top_idx:
            idx = int(i)
            score = float(combined[idx])
            if score < min_score:
                continue
            hits.append(
                RetrievalHit(
                    chunk=self.chunks[idx],
                    score=score,
                    semantic_score=float(sem_scores[idx]),
                    bm25_score=float(bm25_scores[idx]),
                )
            )
            if len(hits) >= k:
                break
        return hits

    def status(self) -> dict:
        sources: dict[str, int] = {}
        for c in self.chunks:
            sources[c.source_type] = sources.get(c.source_type, 0) + 1
        return {
            "chunk_count": len(self.chunks),
            "embedder": self.embedder.name,
            "dims": self.embedder.dims,
            "last_built": self.last_built,
            "last_refreshed": self.last_refreshed,
            "sources": sources,
            "index_dir": self.index_dir,
        }


# ---------------------------------------------------------------------------
# Corpus gatherer + lifespan entry point
# ---------------------------------------------------------------------------


def _gather_corpus_chunks(ai_tools_dir: str) -> list[Chunk]:
    """Load chunks from every corpus source."""
    chunks: list[Chunk] = []

    t0 = time.time()
    chunks.extend(load_fabric_ai_md(ai_tools_dir))
    chunks.extend(load_skills(ai_tools_dir))
    chunks.extend(load_agents(ai_tools_dir))
    chunks.extend(load_fablib_examples(ai_tools_dir))
    chunks.extend(load_site_catalog())

    # User weaves (from storage dirs)
    try:
        from app.settings_manager import get_storage_dir, get_root_storage_dir
        storage_dirs: list[str] = []
        try:
            storage_dirs.append(get_storage_dir())
        except Exception:
            pass
        try:
            root = get_root_storage_dir()
            if root not in storage_dirs:
                storage_dirs.append(root)
        except Exception:
            pass
        chunks.extend(load_weaves(storage_dirs))
    except Exception as e:
        logger.warning("RAG: weave load failed: %s", e)

    logger.info(
        "RAG: gathered %d chunks from corpus in %.2fs",
        len(chunks), time.time() - t0,
    )
    return chunks


def get_index() -> Optional[RAGIndex]:
    """Return the singleton index (may be None if startup failed)."""
    return _INDEX


async def refresh_index_if_stale(max_age: float = 60.0) -> None:
    """Cheap incremental refresh: rescan corpus and re-embed changed chunks.

    Called at the top of each chat turn. If the index is younger than
    ``max_age`` seconds, do nothing.
    """
    global _INDEX
    if _INDEX is None:
        return
    if time.time() - _INDEX.last_refreshed < max_age:
        return
    async with _INDEX_LOCK:
        # Double-check under lock
        if time.time() - _INDEX.last_refreshed < max_age:
            return
        try:
            ai_tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "ai-tools"
            )
            fresh = await asyncio.to_thread(_gather_corpus_chunks, ai_tools_dir)
            await asyncio.to_thread(_INDEX.incremental_refresh, fresh)
        except Exception as e:
            logger.warning("RAG: incremental refresh failed: %s", e)


async def startup_build_index() -> None:
    """Lifespan entry point — build or load the index."""
    global _INDEX
    try:
        from app.settings_manager import get_root_storage_dir
    except Exception:
        return

    try:
        storage_root = get_root_storage_dir()
    except Exception:
        storage_root = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    index_dir = os.path.join(storage_root, ".loomai", "rag_index")
    model_cache = os.path.join(storage_root, ".cache", "fastembed")
    os.makedirs(index_dir, exist_ok=True)
    os.makedirs(model_cache, exist_ok=True)

    def _build_sync():
        embedder = build_embedder(prefer_remote=True, cache_dir=model_cache)
        idx = RAGIndex(index_dir=index_dir, embedder=embedder)
        # Try to load existing index first
        if idx.load():
            # Still do an incremental refresh to pick up any changes
            ai_tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "ai-tools"
            )
            fresh = _gather_corpus_chunks(ai_tools_dir)
            idx.incremental_refresh(fresh)
            return idx
        # Full build
        ai_tools_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "ai-tools"
        )
        chunks = _gather_corpus_chunks(ai_tools_dir)
        idx.build(chunks)
        return idx

    try:
        t0 = time.time()
        idx = await asyncio.to_thread(_build_sync)
        _INDEX = idx
        logger.info(
            "RAG: startup index ready in %.1fs (%d chunks, embedder=%s)",
            time.time() - t0, len(idx.chunks), idx.embedder.name,
        )
    except Exception as e:
        logger.warning("RAG: startup build failed: %s", e, exc_info=True)
        _INDEX = None


# ---------------------------------------------------------------------------
# Retrieval convenience for callers
# ---------------------------------------------------------------------------


def retrieve_for_chat(
    query: str,
    *,
    k: int = 5,
    min_score: float = 0.25,
    weave_bias: bool = False,
) -> list[RetrievalHit]:
    """Retrieve top-K chunks for a chat query.

    When ``weave_bias`` is True, boost weave and example chunks so the
    assistant preferentially surfaces user artifacts and proven code
    patterns over generic reference material.
    """
    idx = get_index()
    if idx is None:
        return []
    hits = idx.retrieve(query, k=k * 2, min_score=min_score)
    if weave_bias:
        for h in hits:
            if h.chunk.source_type in ("weave", "example"):
                h.score += 0.1
        hits.sort(key=lambda h: -h.score)
    return hits[:k]


def format_hits_as_context(hits: list[RetrievalHit], *, max_chars: int = 6000) -> str:
    """Format retrieval hits as a markdown context block for injection."""
    if not hits:
        return ""
    lines = ["## Retrieved Context", ""]
    lines.append(
        "The following passages were retrieved from the LoomAI knowledge base "
        "based on the user's message. Prefer information here over generic "
        "knowledge when answering.\n"
    )
    used = sum(len(l) for l in lines)
    for i, h in enumerate(hits, 1):
        block = (
            f"### [{i}] {h.chunk.source_type}: {h.chunk.section} "
            f"(score={h.score:.2f})\n"
            f"_Source: `{h.chunk.source_path}`_\n\n"
            f"{h.chunk.text}\n"
        )
        if used + len(block) > max_chars:
            lines.append(f"_(+{len(hits) - i + 1} more hits truncated)_\n")
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)
