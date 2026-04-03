"""Tests for Trovi marketplace endpoints — browse, search, download."""

import json
import os
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_trovi_urlopen(artifacts: list[dict]):
    """Create a mock for urllib.request.urlopen returning Trovi artifact data."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"artifacts": artifacts}).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _mock_trovi_single(artifact: dict):
    """Create a mock for urllib.request.urlopen returning a single artifact."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(artifact).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


SAMPLE_ARTIFACTS = [
    {
        "uuid": "artifact-001",
        "title": "Hello Chameleon",
        "short_description": "A starter experiment for Chameleon Cloud",
        "tags": ["beginner", "tutorial"],
        "authors": [{"full_name": "Alice Researcher"}],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-06-01T00:00:00Z",
        "visibility": "public",
        "versions": [{"slug": "v1"}],
    },
    {
        "uuid": "artifact-002",
        "title": "Networking Performance Test",
        "short_description": "Measure network throughput between nodes",
        "tags": ["networking", "performance"],
        "authors": [{"full_name": "Bob Engineer"}],
        "created_at": "2025-02-01T00:00:00Z",
        "updated_at": "2025-07-01T00:00:00Z",
        "visibility": "public",
        "versions": [{"slug": "v1"}, {"slug": "v2"}],
    },
    {
        "uuid": "artifact-003",
        "title": "GPU Benchmarking Suite",
        "short_description": "Benchmark GPU performance on Chameleon",
        "tags": ["gpu", "performance", "benchmark"],
        "authors": [{"full_name": "Carol Scientist"}],
        "created_at": "2025-03-01T00:00:00Z",
        "updated_at": "2025-08-01T00:00:00Z",
        "visibility": "public",
        "versions": [],
    },
]


# ---------------------------------------------------------------------------
# GET /api/trovi/artifacts
# ---------------------------------------------------------------------------

class TestListTroviArtifacts:
    def test_returns_artifact_list(self, client):
        """GET /api/trovi/artifacts should return a list of artifacts."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert "artifacts" in data
        assert "total" in data
        assert data["total"] == 3
        assert len(data["artifacts"]) == 3

    def test_artifact_has_expected_fields(self, client):
        """Each artifact should have uuid, title, tags, authors, source."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts")
        art = resp.json()["artifacts"][0]
        assert art["uuid"] == "artifact-001"
        assert art["title"] == "Hello Chameleon"
        assert art["source"] == "trovi"
        assert "Alice Researcher" in art["authors"]
        assert art["versions"] == 1

    def test_search_by_query(self, client):
        """GET /api/trovi/artifacts?q=network should filter by search."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts?q=network")
        data = resp.json()
        assert data["total"] == 1
        assert data["artifacts"][0]["uuid"] == "artifact-002"

    def test_search_case_insensitive(self, client):
        """Search should be case-insensitive."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts?q=GPU")
        data = resp.json()
        assert data["total"] == 1
        assert data["artifacts"][0]["uuid"] == "artifact-003"

    def test_filter_by_tag(self, client):
        """GET /api/trovi/artifacts?tag=performance should filter by tag."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts?tag=performance")
        data = resp.json()
        assert data["total"] == 2
        uuids = [a["uuid"] for a in data["artifacts"]]
        assert "artifact-002" in uuids
        assert "artifact-003" in uuids

    def test_pagination_limit(self, client):
        """GET /api/trovi/artifacts?limit=1 should limit results."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts?limit=1")
        data = resp.json()
        assert data["total"] == 3  # Total before pagination
        assert len(data["artifacts"]) == 1

    def test_pagination_offset(self, client):
        """GET /api/trovi/artifacts?offset=2&limit=10 should skip first items."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts?offset=2&limit=10")
        data = resp.json()
        assert data["total"] == 3
        assert len(data["artifacts"]) == 1
        assert data["artifacts"][0]["uuid"] == "artifact-003"

    def test_api_error_returns_502(self, client):
        """GET /api/trovi/artifacts should return 502 on API error."""
        with patch("app.routes.trovi.urllib.request.urlopen",
                    side_effect=Exception("Connection timeout")):
            resp = client.get("/api/trovi/artifacts")
        assert resp.status_code == 502
        assert "error" in resp.json()

    def test_combined_query_and_tag(self, client):
        """Search with both q and tag should apply both filters."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts?q=benchmark&tag=gpu")
        data = resp.json()
        assert data["total"] == 1
        assert data["artifacts"][0]["uuid"] == "artifact-003"


# ---------------------------------------------------------------------------
# GET /api/trovi/artifacts/{uuid}
# ---------------------------------------------------------------------------

class TestGetTroviArtifact:
    def test_returns_single_artifact(self, client):
        """GET /api/trovi/artifacts/{uuid} should return artifact details."""
        artifact = {
            "uuid": "artifact-001",
            "title": "Hello Chameleon",
            "short_description": "A starter experiment",
            "tags": ["beginner"],
            "authors": [{"full_name": "Alice"}],
            "versions": [{"slug": "v1", "contents": {"urn": "urn:trovi:..."}}],
        }
        mock_resp = _mock_trovi_single(artifact)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/artifacts/artifact-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["uuid"] == "artifact-001"
        assert data["source"] == "trovi"

    def test_not_found_returns_error(self, client):
        """GET /api/trovi/artifacts/{uuid} for missing artifact returns error."""
        import urllib.error
        http_error = urllib.error.HTTPError(
            "https://trovi.chameleoncloud.org/artifacts/missing",
            404, "Not Found", {}, None
        )
        with patch("app.routes.trovi.urllib.request.urlopen", side_effect=http_error):
            resp = client.get("/api/trovi/artifacts/missing-uuid")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/trovi/tags
# ---------------------------------------------------------------------------

class TestListTroviTags:
    def test_returns_unique_tags(self, client):
        """GET /api/trovi/tags should return sorted unique tags."""
        mock_resp = _mock_trovi_urlopen(SAMPLE_ARTIFACTS)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.get("/api/trovi/tags")
        assert resp.status_code == 200
        data = resp.json()
        tags = data["tags"]
        assert isinstance(tags, list)
        assert "beginner" in tags
        assert "networking" in tags
        assert "gpu" in tags
        # Tags should be sorted
        assert tags == sorted(tags)
        # No duplicates
        assert len(tags) == len(set(tags))

    def test_tags_api_error(self, client):
        """GET /api/trovi/tags should return 502 on API error."""
        with patch("app.routes.trovi.urllib.request.urlopen",
                    side_effect=Exception("Timeout")):
            resp = client.get("/api/trovi/tags")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/trovi/artifacts/{uuid}/get
# ---------------------------------------------------------------------------

class TestDownloadTroviArtifact:
    def test_download_creates_directory(self, client, storage_dir):
        """POST /api/trovi/artifacts/{uuid}/get should create artifact dir."""
        artifact = {
            "uuid": "artifact-001",
            "title": "Hello Chameleon",
            "short_description": "A starter experiment",
            "tags": ["beginner"],
            "authors": [{"full_name": "Alice"}],
            "versions": [],
        }
        mock_resp = _mock_trovi_single(artifact)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp):
            resp = client.post("/api/trovi/artifacts/artifact-001/get")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "downloaded"
        assert data["source"] == "trovi"
        assert data["title"] == "Hello Chameleon"

        # Check that directory was created with weave.json
        dest = os.path.join(str(storage_dir), "my_artifacts", data["dir_name"])
        assert os.path.isdir(dest)
        weave_json = os.path.join(dest, "weave.json")
        assert os.path.isfile(weave_json)
        with open(weave_json) as f:
            meta = json.load(f)
        assert meta["source"] == "trovi"
        assert meta["trovi_uuid"] == "artifact-001"

    def test_download_with_git_content(self, client, storage_dir):
        """POST /api/trovi/artifacts/{uuid}/get with git URN should attempt clone."""
        artifact = {
            "uuid": "artifact-002",
            "title": "Git Experiment",
            "short_description": "Has git content",
            "tags": [],
            "authors": [],
            "versions": [{
                "slug": "v1",
                "contents": {"urn": "urn:trovi:contents:git:https://github.com/example/repo@abc123"},
            }],
        }
        mock_resp = _mock_trovi_single(artifact)
        with patch("app.routes.trovi.urllib.request.urlopen", return_value=mock_resp), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            resp = client.post("/api/trovi/artifacts/artifact-002/get")
        assert resp.status_code == 200
        # Verify git clone was attempted
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "git" in call_args[0][0]
        assert "clone" in call_args[0][0]

    def test_download_api_error(self, client):
        """POST /api/trovi/artifacts/{uuid}/get with API error returns 400."""
        with patch("app.routes.trovi.urllib.request.urlopen",
                    side_effect=Exception("Not found")):
            resp = client.post("/api/trovi/artifacts/bad-uuid/get")
        assert resp.status_code == 400
        assert "error" in resp.json()
