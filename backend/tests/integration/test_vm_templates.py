"""Tests for VM template CRUD."""

import json


class TestListVMTemplates:
    def test_list_returns_array(self, client):
        resp = client.get("/api/vm-templates")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCreateVMTemplate:
    def test_create_vm_template(self, client):
        resp = client.post("/api/vm-templates",
                           json={
                               "name": "My_VM",
                               "node_def": {
                                   "image": "default_ubuntu_22",
                                   "cores": 4,
                                   "ram": 16,
                                   "disk": 50,
                                   "boot_config": {
                                       "uploads": [],
                                       "commands": ["apt update"],
                                       "network": [],
                                   }
                               }
                           })
        assert resp.status_code == 200

    def test_created_template_appears_in_list(self, client):
        client.post("/api/vm-templates",
                    json={
                        "name": "ListCheck",
                        "node_def": {
                            "image": "default_ubuntu_22",
                            "boot_config": {"uploads": [], "commands": [], "network": []},
                        }
                    })
        resp = client.get("/api/vm-templates")
        names = [t["name"] for t in resp.json()]
        assert "ListCheck" in names


class TestGetVMTemplate:
    def test_get_returns_detail(self, client):
        client.post("/api/vm-templates",
                    json={
                        "name": "Detail_VM",
                        "node_def": {
                            "image": "default_ubuntu_22",
                            "boot_config": {"uploads": [], "commands": [], "network": []},
                        }
                    })
        resp = client.get("/api/vm-templates/Detail_VM")
        assert resp.status_code == 200
        data = resp.json()
        assert data["image"] == "default_ubuntu_22"


class TestDeleteVMTemplate:
    def test_delete_removes_template(self, client, storage_dir):
        # Create a VM template directory
        tmpl_dir = storage_dir / "my_artifacts" / "Del_VM"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "vm-template.json").write_text(json.dumps({
            "image": "default_ubuntu_22",
            "boot_config": {"uploads": [], "commands": [], "network": []},
        }))
        (tmpl_dir / "metadata.json").write_text(json.dumps({
            "name": "Del_VM",
            "category": "vm-template",
        }))

        resp = client.delete("/api/vm-templates/Del_VM")
        assert resp.status_code == 200
        assert not tmpl_dir.exists()
