from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from omnimem.cli import _maybe_run_startup_sync_guide


class CLIStartupGuideTest(unittest.TestCase):
    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(startup_guide=True, no_daemon=False)

    def _cfg(self) -> dict[str, object]:
        return {"sync": {"github": {"remote_url": ""}}}

    def _cfg_path(self, td: str) -> Path:
        p = Path(td) / "omnimem.json"
        p.write_text(json.dumps({"sync": {"github": {"remote_url": ""}}}), encoding="utf-8")
        return p

    def test_autorun_when_ready(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-startup-guide.") as td:
            cfg = self._cfg()
            cfg_path = self._cfg_path(td)
            diag = {
                "oauth_client_id_available": True,
                "recommended_provider": "vercel",
                "providers": [{"provider": "vercel", "installed": True, "logged_in": True, "login_hint": "vercel login"}],
            }
            with (
                patch("omnimem.cli.sys.stdin.isatty", return_value=True),
                patch("omnimem.cli._truthy_env", return_value=False),
                patch("omnimem.cli._oauth_broker_doctor_data", return_value=diag),
                patch("omnimem.cli.cmd_oauth_broker_auto", return_value=0) as m_auto,
            ):
                _maybe_run_startup_sync_guide(self._args(), cfg, cfg_path)
            self.assertEqual(m_auto.call_count, 1)
            call_args = m_auto.call_args.args[0]
            self.assertEqual(str(call_args.provider), "vercel")

    def test_missing_client_id_then_continue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-startup-guide.") as td:
            cfg = self._cfg()
            cfg_path = self._cfg_path(td)
            d1 = {
                "oauth_client_id_available": False,
                "recommended_provider": "cloudflare",
                "providers": [{"provider": "cloudflare", "installed": True, "logged_in": True, "login_hint": "wrangler login"}],
            }
            d2 = {
                "oauth_client_id_available": True,
                "recommended_provider": "cloudflare",
                "providers": [{"provider": "cloudflare", "installed": True, "logged_in": True, "login_hint": "wrangler login"}],
            }
            with (
                patch("omnimem.cli.sys.stdin.isatty", return_value=True),
                patch("omnimem.cli._truthy_env", return_value=False),
                patch("omnimem.cli._oauth_broker_doctor_data", side_effect=[d1, d2]),
                patch("builtins.input", side_effect=["Iv1.test-client-id"]),
                patch("omnimem.cli.cmd_oauth_broker_auto", return_value=0) as m_auto,
            ):
                _maybe_run_startup_sync_guide(self._args(), cfg, cfg_path)
            self.assertEqual(m_auto.call_count, 1)
            call_args = m_auto.call_args.args[0]
            self.assertEqual(str(call_args.client_id), "Iv1.test-client-id")

    def test_provider_login_then_continue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-startup-guide.") as td:
            cfg = self._cfg()
            cfg_path = self._cfg_path(td)
            d1 = {
                "oauth_client_id_available": True,
                "recommended_provider": "vercel",
                "providers": [{"provider": "vercel", "installed": True, "logged_in": False, "login_hint": "vercel login"}],
            }
            d2 = {
                "oauth_client_id_available": True,
                "recommended_provider": "vercel",
                "providers": [{"provider": "vercel", "installed": True, "logged_in": True, "login_hint": "vercel login"}],
            }
            with (
                patch("omnimem.cli.sys.stdin.isatty", return_value=True),
                patch("omnimem.cli._truthy_env", return_value=False),
                patch("omnimem.cli._oauth_broker_doctor_data", side_effect=[d1, d2]),
                patch("builtins.input", side_effect=["y"]),
                patch("omnimem.cli.subprocess.run", return_value=SimpleNamespace(returncode=0)) as m_run,
                patch("omnimem.cli.cmd_oauth_broker_auto", return_value=0) as m_auto,
            ):
                _maybe_run_startup_sync_guide(self._args(), cfg, cfg_path)
            self.assertEqual(m_run.call_count, 1)
            self.assertEqual(m_auto.call_count, 1)

    def test_provider_missing_and_skip_wizard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-startup-guide.") as td:
            cfg = self._cfg()
            cfg_path = self._cfg_path(td)
            diag = {
                "oauth_client_id_available": True,
                "recommended_provider": "cloudflare",
                "providers": [{"provider": "cloudflare", "installed": False, "logged_in": False, "login_hint": "wrangler login"}],
            }
            with (
                patch("omnimem.cli.sys.stdin.isatty", return_value=True),
                patch("omnimem.cli._truthy_env", return_value=False),
                patch("omnimem.cli._oauth_broker_doctor_data", return_value=diag),
                patch("builtins.input", side_effect=["n"]),
                patch("omnimem.cli.cmd_oauth_broker_wizard", return_value=0) as m_wz,
                patch("omnimem.cli.cmd_oauth_broker_auto", return_value=0) as m_auto,
            ):
                _maybe_run_startup_sync_guide(self._args(), cfg, cfg_path)
            self.assertEqual(m_wz.call_count, 0)
            self.assertEqual(m_auto.call_count, 0)

    def test_never_choice_disables_guide(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-startup-guide.") as td:
            cfg = self._cfg()
            cfg_path = self._cfg_path(td)
            diag = {"oauth_client_id_available": False, "recommended_provider": "cloudflare", "providers": []}
            with (
                patch("omnimem.cli.sys.stdin.isatty", return_value=True),
                patch("omnimem.cli._truthy_env", return_value=False),
                patch("omnimem.cli._oauth_broker_doctor_data", return_value=diag),
                patch("builtins.input", side_effect=["never"]),
            ):
                _maybe_run_startup_sync_guide(self._args(), cfg, cfg_path)
            self.assertTrue(bool(cfg.get("setup", {}).get("startup_guide_disabled", False)))


if __name__ == "__main__":
    unittest.main()
