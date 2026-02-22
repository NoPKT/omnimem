from __future__ import annotations

import unittest

from omnimem.oauth import _detect_broker_url_from_deploy_output, _extract_https_urls
from omnimem.cli import (


    _find_provider_status,
    _provider_install_hint,
    _startup_guide_can_autorun,
)


class CLIOAuthBrokerTest(unittest.TestCase):
    def test_extract_https_urls(self) -> None:
        txt = "deploy ok: https://a.workers.dev/path, and docs https://example.com/help."
        urls = _extract_https_urls(txt)
        self.assertEqual(urls, ["https://a.workers.dev/path", "https://example.com/help"])

    def test_detect_provider_specific_url(self) -> None:
        out = {
            "stdout": "Inspect: https://dashboard.example.com and live https://my-app.vercel.app",
            "stderr": "",
        }
        u = _detect_broker_url_from_deploy_output("vercel", out)
        self.assertEqual(u, "https://my-app.vercel.app")

    def test_detect_fallback_url(self) -> None:
        out = {"stdout": "done at https://example.net/service", "stderr": ""}
        u = _detect_broker_url_from_deploy_output("cloudflare", out)
        self.assertEqual(u, "https://example.net/service")

    def test_startup_guide_can_autorun_true(self) -> None:
        diag = {
            "oauth_client_id_available": True,
            "providers": [
                {"provider": "cloudflare", "installed": True, "logged_in": True},
            ],
        }
        self.assertTrue(_startup_guide_can_autorun(diag))

    def test_startup_guide_can_autorun_false(self) -> None:
        diag = {
            "oauth_client_id_available": False,
            "providers": [
                {"provider": "cloudflare", "installed": True, "logged_in": True},
            ],
        }
        self.assertFalse(_startup_guide_can_autorun(diag))

    def test_provider_install_hint(self) -> None:
        self.assertEqual(_provider_install_hint("cloudflare"), "npm i -g wrangler")
        self.assertEqual(_provider_install_hint("vercel"), "npm i -g vercel")

    def test_find_provider_status(self) -> None:
        diag = {
            "providers": [
                {"provider": "cloudflare", "installed": True, "logged_in": False},
                {"provider": "vercel", "installed": True, "logged_in": True},
            ]
        }
        p = _find_provider_status(diag, "vercel")
        self.assertTrue(bool(p.get("logged_in")))


if __name__ == "__main__":
    unittest.main()
