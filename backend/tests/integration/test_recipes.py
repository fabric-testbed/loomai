"""Tests for recipe CRUD endpoints."""

import json


class TestListRecipes:
    def test_list_empty_returns_array(self, client):
        resp = client.get("/api/recipes")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_returns_recipe_when_exists(self, client, storage_dir):
        # Create a recipe artifact directory with recipe.json
        recipe_dir = storage_dir / "my_artifacts" / "test_recipe"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        (recipe_dir / "recipe.json").write_text(json.dumps({
            "name": "Test Recipe",
            "version": "1.0",
            "description": "A test recipe",
            "image_patterns": {"ubuntu": "install.sh"},
            "starred": True,
            "steps": [],
        }))

        # Invalidate the recipes cache so the new recipe is picked up
        from app.routes.recipes import _invalidate_recipes_cache
        _invalidate_recipes_cache()

        resp = client.get("/api/recipes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        names = [r["name"] for r in data]
        assert "Test Recipe" in names
        recipe = next(r for r in data if r["name"] == "Test Recipe")
        assert recipe["version"] == "1.0"
        assert recipe["dir_name"] == "test_recipe"


class TestGetRecipe:
    def test_get_existing_recipe(self, client, storage_dir):
        recipe_dir = storage_dir / "my_artifacts" / "my_recipe"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        (recipe_dir / "recipe.json").write_text(json.dumps({
            "name": "My Recipe",
            "version": "2.0",
            "description": "Detailed recipe",
            "image_patterns": {"*": "run.sh"},
            "steps": [{"type": "execute", "command": "echo hello"}],
        }))

        resp = client.get("/api/recipes/my_recipe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Recipe"
        assert data["version"] == "2.0"
        assert data["dir_name"] == "my_recipe"
        assert len(data["steps"]) == 1

    def test_get_missing_recipe_returns_404(self, client):
        resp = client.get("/api/recipes/nonexistent")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"] == "RECIPE_NOT_FOUND"
        assert "not found" in detail["detail"]
        assert detail["recipe"] == "nonexistent"


class TestErrorEnvelopes:
    def test_recipe_not_found_envelope(self, client):
        resp = client.patch("/api/recipes/does_not_exist", json={"starred": True})
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"] == "RECIPE_NOT_FOUND"
        assert "not found" in detail["detail"]
        assert detail["recipe"] == "does_not_exist"

    def test_invalid_recipe_name_envelope(self):
        import pytest
        from fastapi import HTTPException
        from app.routes.recipes import _sanitize_name, _validate_path

        with pytest.raises(HTTPException) as exc_info:
            _sanitize_name("   ")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "RECIPE_NAME_INVALID"
        assert "valid characters" in exc_info.value.detail["detail"]

        with pytest.raises(HTTPException) as exc_info:
            _validate_path("/tmp/artifacts", "../escape")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "RECIPE_NAME_INVALID"
        assert "artifacts directory" in exc_info.value.detail["detail"]
        assert exc_info.value.detail["recipe"] == "../escape"


class TestUpdateRecipe:
    def test_toggle_starred(self, client, storage_dir):
        recipe_dir = storage_dir / "my_artifacts" / "star_recipe"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        (recipe_dir / "recipe.json").write_text(json.dumps({
            "name": "Star Recipe",
            "starred": True,
            "steps": [],
        }))

        # Un-star the recipe
        resp = client.patch("/api/recipes/star_recipe",
                            json={"starred": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["starred"] is False

        # Verify it persisted on disk
        with open(recipe_dir / "recipe.json") as f:
            saved = json.load(f)
        assert saved["starred"] is False

        # Re-star it
        resp = client.patch("/api/recipes/star_recipe",
                            json={"starred": True})
        assert resp.status_code == 200
        assert resp.json()["starred"] is True
