from django.test import Client

from zerver.lib.test_classes import ZulipTestCase


class NbCsrfTest(ZulipTestCase):
    def test_session_token_authorizes_post(self) -> None:
        self.login("hamlet")
        self.assert_json_success(self.client_get("/json/nb/csrf", intentionally_undocumented=True))
        client = Client(enforce_csrf_checks=True)
        client.cookies = self.client.cookies

        response = client.get("/json/nb/csrf", HTTP_HOST="zulip.testserver")
        self.assert_json_success(response)
        token = response.json()["csrf_token"]
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        self.assertNotIn("Access-Control-Allow-Origin", response)

        # Prove the POST needs CSRF before trying the returned token.
        with self.assertLogs("django.security.csrf", level="WARNING"):
            response = client.post(
                "/json/users/me/status",
                {"status_text": "Testing"},
                HTTP_HOST="zulip.testserver",
            )
        self.assertEqual(response.status_code, 403)
        response = client.post(
            "/json/users/me/status",
            {"status_text": "Testing"},
            HTTP_HOST="zulip.testserver",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assert_json_success(response)

    def test_signed_out(self) -> None:
        self.assert_json_error(
            self.client_get("/json/nb/csrf"),
            "Not logged in: API authentication or user session required",
            status_code=401,
        )

    def test_get_only(self) -> None:
        self.login("hamlet")
        self.assertEqual(self.client_post("/json/nb/csrf").status_code, 405)

    def test_no_api_route(self) -> None:
        self.assertEqual(self.client_get("/api/v1/nb/csrf").status_code, 404)
