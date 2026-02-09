from __future__ import annotations

import os
import unittest

from omnimem.webui import _is_local_bind_host, _resolve_auth_token


class WebUISecurityTest(unittest.TestCase):
    def test_local_bind_host_detection(self) -> None:
        self.assertTrue(_is_local_bind_host("127.0.0.1"))
        self.assertTrue(_is_local_bind_host("localhost"))
        self.assertTrue(_is_local_bind_host("::1"))
        self.assertFalse(_is_local_bind_host("0.0.0.0"))
        self.assertFalse(_is_local_bind_host("192.168.1.10"))

    def test_auth_token_resolution_precedence(self) -> None:
        cfg = {"webui": {"auth_token": "cfg-token"}}
        old = os.environ.get("OMNIMEM_WEBUI_TOKEN")
        try:
            os.environ["OMNIMEM_WEBUI_TOKEN"] = "env-token"
            self.assertEqual(_resolve_auth_token(cfg, None), "env-token")
            self.assertEqual(_resolve_auth_token(cfg, "arg-token"), "arg-token")
        finally:
            if old is None:
                os.environ.pop("OMNIMEM_WEBUI_TOKEN", None)
            else:
                os.environ["OMNIMEM_WEBUI_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
