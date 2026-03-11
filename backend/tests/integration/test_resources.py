"""Tests for resource endpoints — sites, images, component models."""


class TestListSites:
    def test_returns_list(self, client):
        resp = client.get("/api/sites")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_site_has_expected_fields(self, client):
        resp = client.get("/api/sites")
        site = resp.json()[0]
        assert "name" in site
        assert "state" in site
        assert "cores_available" in site


class TestListImages:
    def test_returns_list(self, client):
        resp = client.get("/api/images")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "default_ubuntu_22" in data

    def test_contains_common_images(self, client):
        images = client.get("/api/images").json()
        assert "default_ubuntu_22" in images
        assert "default_rocky_9" in images


class TestListComponentModels:
    def test_returns_list(self, client):
        resp = client.get("/api/component-models")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_model_has_expected_fields(self, client):
        models = client.get("/api/component-models").json()
        model = models[0]
        assert "model" in model
        assert "type" in model
        assert "description" in model

    def test_includes_known_models(self, client):
        models = client.get("/api/component-models").json()
        model_names = [m["model"] for m in models]
        assert "NIC_Basic" in model_names
        assert "GPU_TeslaT4" in model_names
        assert "GPU_RTX6000" in model_names
