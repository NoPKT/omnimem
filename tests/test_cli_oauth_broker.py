from __future__ import annotations

import unittest

from omnimem.cli import _detect_broker_url_from_deploy_output, _extract_https_urls


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


if __name__ == "__main__":
    unittest.main()
