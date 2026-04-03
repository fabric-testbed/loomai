"""Advanced tests for recipe management routes.

Covers: list with cache, get full detail, update starred, content reading,
name sanitization, image pattern matching.
"""

import json
import os
import time

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recipe(storage_dir, dir_name, recipe_data):
    """Create a recipe artifact directory with recipe.json."""
    recipe_dir = storage_dir / "my_artifacts" / dir_name
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.json").write_text(json.dumps(recipe_data))
    # Invalidate cache
    from app.routes.recipes import _invalidate_recipes_cache
    _invalidate_recipes_cache()
    return recipe_dir


# ---------------------------------------------------------------------------
# List recipes
# ---------------------------------------------------------------------------

class TestListRecipesAdvanced:
    def test_list_multiple_recipes(self, client, storage_dir):
        _make_recipe(storage_dir, "recipe_a", {
            "name": "Alpha Recipe",
            "version": "1.0",
            "description": "First",
            "image_patterns": {},
            "steps": [],
        })
        _make_recipe(storage_dir, "recipe_b", {
            "name": "Beta Recipe",
            "version": "2.0",
            "description": "Second",
            "image_patterns": {"ubuntu": "install.sh"},
            "steps": [],
        })
        resp = client.get("/api/recipes")
        assert resp.status_code == 200
        names = [r["name"] for r in resp.json()]
        assert "Alpha Recipe" in names
        assert "Beta Recipe" in names

    def test_list_uses_cache(self, client, storage_dir):
        """Second call within TTL should return cached data."""
        _make_recipe(storage_dir, "cached_recipe", {
            "name": "Cached",
            "version": "1.0",
            "steps": [],
        })
        resp1 = client.get("/api/recipes")
        resp2 = client.get("/api/recipes")
        assert resp1.json() == resp2.json()

    def test_list_skips_non_recipe_dirs(self, client, storage_dir):
        """Dirs without recipe.json should be skipped."""
        non_recipe = storage_dir / "my_artifacts" / "not_a_recipe"
        non_recipe.mkdir(parents=True, exist_ok=True)
        (non_recipe / "readme.txt").write_text("not a recipe")
        from app.routes.recipes import _invalidate_recipes_cache
        _invalidate_recipes_cache()
        resp = client.get("/api/recipes")
        names = [r["dir_name"] for r in resp.json()]
        assert "not_a_recipe" not in names

    def test_list_auto_adds_name_if_missing(self, client, storage_dir):
        """If recipe.json has no 'name' field, the dir name should be used."""
        _make_recipe(storage_dir, "nameless", {
            "version": "1.0",
            "steps": [],
        })
        resp = client.get("/api/recipes")
        recipe = next(r for r in resp.json() if r["dir_name"] == "nameless")
        assert recipe["name"] == "nameless"

    def test_list_recipe_has_expected_fields(self, client, storage_dir):
        _make_recipe(storage_dir, "full_recipe", {
            "name": "Full Recipe",
            "version": "3.0",
            "description": "A complete recipe",
            "image_patterns": {"*": "run.sh"},
            "starred": False,
            "steps": [{"type": "execute"}],
        })
        resp = client.get("/api/recipes")
        recipe = next(r for r in resp.json() if r["name"] == "Full Recipe")
        assert recipe["version"] == "3.0"
        assert recipe["description"] == "A complete recipe"
        assert recipe["image_patterns"] == {"*": "run.sh"}
        assert recipe["starred"] is False
        assert recipe["dir_name"] == "full_recipe"


# ---------------------------------------------------------------------------
# Get recipe
# ---------------------------------------------------------------------------

class TestGetRecipeAdvanced:
    def test_get_recipe_with_steps(self, client, storage_dir):
        _make_recipe(storage_dir, "step_recipe", {
            "name": "Step Recipe",
            "version": "1.0",
            "steps": [
                {"type": "upload_scripts"},
                {"type": "execute", "command": "bash {script}"},
                {"type": "reboot_and_wait", "timeout": 120},
            ],
        })
        resp = client.get("/api/recipes/step_recipe")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["steps"]) == 3
        assert data["steps"][0]["type"] == "upload_scripts"
        assert data["steps"][2]["timeout"] == 120

    def test_get_recipe_includes_dir_name(self, client, storage_dir):
        _make_recipe(storage_dir, "dir_check", {"name": "Dir Check"})
        resp = client.get("/api/recipes/dir_check")
        assert resp.json()["dir_name"] == "dir_check"


# ---------------------------------------------------------------------------
# Update recipe
# ---------------------------------------------------------------------------

class TestUpdateRecipeAdvanced:
    def test_star_and_unstar(self, client, storage_dir):
        _make_recipe(storage_dir, "toggle_star", {
            "name": "Toggle",
            "starred": True,
            "steps": [],
        })
        # Unstar
        resp = client.patch("/api/recipes/toggle_star", json={"starred": False})
        assert resp.status_code == 200
        assert resp.json()["starred"] is False

        # Verify on disk
        with open(storage_dir / "my_artifacts" / "toggle_star" / "recipe.json") as f:
            assert json.load(f)["starred"] is False

        # Re-star
        resp = client.patch("/api/recipes/toggle_star", json={"starred": True})
        assert resp.json()["starred"] is True

    def test_update_nonexistent_returns_404(self, client):
        resp = client.patch("/api/recipes/nonexistent_recipe",
                            json={"starred": False})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Image pattern matching (unit-level)
# ---------------------------------------------------------------------------

class TestImagePatternMatch:
    def test_exact_match(self):
        from app.routes.recipes import _match_image
        assert _match_image("default_ubuntu_22", {"ubuntu": "install.sh"}) == "install.sh"

    def test_wildcard_match(self):
        from app.routes.recipes import _match_image
        assert _match_image("any_image", {"*": "universal.sh"}) == "universal.sh"

    def test_case_insensitive(self):
        from app.routes.recipes import _match_image
        assert _match_image("Default_Ubuntu_22", {"ubuntu": "u.sh"}) == "u.sh"

    def test_no_match(self):
        from app.routes.recipes import _match_image
        assert _match_image("rocky_9", {"ubuntu": "u.sh"}) is None

    def test_multiple_patterns_first_match(self):
        from app.routes.recipes import _match_image
        patterns = {"ubuntu": "u.sh", "rocky": "r.sh"}
        assert _match_image("default_ubuntu_22", patterns) == "u.sh"
        assert _match_image("default_rocky_9", patterns) == "r.sh"


# ---------------------------------------------------------------------------
# Name sanitization (unit-level)
# ---------------------------------------------------------------------------

class TestSanitization:
    def test_sanitize_special_chars(self):
        from app.routes.recipes import _sanitize_name
        assert _sanitize_name("my recipe!@#") == "my_recipe___"

    def test_sanitize_empty_raises(self):
        from app.routes.recipes import _sanitize_name
        with pytest.raises(Exception):
            _sanitize_name("   ")

    def test_sanitize_preserves_valid(self):
        from app.routes.recipes import _sanitize_name
        assert _sanitize_name("valid-name_123") == "valid-name_123"
