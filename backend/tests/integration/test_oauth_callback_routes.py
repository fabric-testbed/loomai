"""The OAuth callback must refuse token deliveries this browser did not start."""
from unittest.mock import patch


class TestOAuthCallbackFailsClosed:
    def test_get_without_state_cookie_is_rejected(self, client):
        with patch("app.routes.config._process_oauth_callback") as process:
            resp = client.get("/api/config/callback", params={"id_token": "attacker-token"},
                              follow_redirects=False)
        assert resp.status_code == 403
        process.assert_not_called()

    def test_get_with_cookie_but_no_state_is_rejected(self, client):
        client.cookies.set("loomai_oauth_state", "abc")
        with patch("app.routes.config._process_oauth_callback") as process:
            resp = client.get("/api/config/callback", params={"id_token": "t"},
                              follow_redirects=False)
        assert resp.status_code == 403
        process.assert_not_called()

    def test_post_without_state_is_rejected(self, client):
        with patch("app.routes.config._process_oauth_callback") as process:
            resp = client.post("/api/config/callback", params={"id_token": "t"},
                               follow_redirects=False)
        assert resp.status_code == 403
        process.assert_not_called()

    def test_matching_state_is_processed(self, client):
        from fastapi.responses import RedirectResponse
        login = client.get("/api/config/login", params={"origin": "http://localhost:3000"})
        assert login.status_code == 200
        state = login.cookies.get("loomai_oauth_state")
        # The state rides inside the URL-encoded redirect_uri, so CM echoes it back.
        assert state and f"state%3D{state}" in login.json()["login_url"]

        with patch("app.routes.config._process_oauth_callback",
                   return_value=RedirectResponse(url="/?configLogin=success")) as process:
            resp = client.get("/api/config/callback",
                              params={"id_token": "t", "state": state},
                              follow_redirects=False)
        assert resp.status_code in (302, 307)
        process.assert_called_once()
        # The one-shot state cookie is cleared after use.
        assert "loomai_oauth_state" in resp.headers.get("set-cookie", "")
