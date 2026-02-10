from __future__ import annotations

import os
import unittest

from omnimem.webui import _is_local_bind_host, _resolve_auth_token
from omnimem.webui import _validate_webui_bind_security


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

    def test_non_local_bind_requires_token(self) -> None:
        # If the user explicitly allows non-local binds, require a token so the API isn't wide open.
        with self.assertRaises(ValueError):
            _validate_webui_bind_security(
                host="0.0.0.0",
                allow_non_localhost=True,
                resolved_auth_token="",
            )
        # Local bind can be tokenless.
        _validate_webui_bind_security(
            host="127.0.0.1",
            allow_non_localhost=False,
            resolved_auth_token="",
        )
        # Non-local bind with token is allowed (assuming allow_non_localhost=True).
        _validate_webui_bind_security(
            host="0.0.0.0",
            allow_non_localhost=True,
            resolved_auth_token="t",
        )


if __name__ == "__main__":
    unittest.main()
