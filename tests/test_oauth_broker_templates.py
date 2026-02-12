from __future__ import annotations

from pathlib import Path
import unittest


class OAuthBrokerTemplatesTest(unittest.TestCase):
    def test_template_files_exist(self) -> None:
        root = Path(__file__).resolve().parent.parent
        base = root / "examples" / "oauth-broker"

        required = [
            base / "cloudflare-worker" / "wrangler.toml",
            base / "cloudflare-worker" / "cloudflare-worker.js",
            base / "vercel" / "vercel.json",
            base / "vercel" / "api" / "v1" / "github" / "device" / "start.js",
            base / "vercel" / "api" / "v1" / "github" / "device" / "poll.js",
            base / "railway" / "railway.json",
            base / "railway" / "package.json",
            base / "railway" / "server.js",
            base / "fly" / "fly.toml",
            base / "fly" / "Dockerfile",
            base / "fly" / "package.json",
            base / "fly" / "server.js",
        ]

        missing = [str(p.relative_to(root)) for p in required if not p.exists()]
        self.assertEqual(missing, [], msg=f"missing oauth-broker template files: {missing}")


if __name__ == "__main__":
    unittest.main()

