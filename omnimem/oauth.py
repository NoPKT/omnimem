from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .core import load_config, save_config, load_config_with_path

def _oauth_broker_examples_root() -> Path:
    return Path(__file__).resolve().parent.parent / "examples" / "oauth-broker"

def _oauth_broker_template_dir(provider: str) -> Path:
    p = str(provider or "").strip().lower()
    if p == "cloudflare":
        return _oauth_broker_examples_root() / "cloudflare-worker"
    if p == "vercel":
        return _oauth_broker_examples_root() / "vercel"
    if p == "railway":
        return _oauth_broker_examples_root() / "railway"
    if p == "fly":
        return _oauth_broker_examples_root() / "fly"
    raise ValueError(f"unsupported provider: {provider}")

def _oauth_broker_deploy_hint(provider: str, workdir: Path) -> list[str]:
    p = str(provider or "").strip().lower()
    wd = str(workdir)
    if p == "cloudflare":
        return [
            f"cd {wd}",
            "wrangler deploy",
        ]
    if p == "vercel":
        return [
            f"cd {wd}",
            "vercel deploy --prod --yes",
        ]
    if p == "railway":
        return [
            f"cd {wd}",
            "railway up",
        ]
    if p == "fly":
        return [
            f"cd {wd}",
            "flyctl deploy",
        ]
    return []

def _write_cloudflare_wrangler_toml(*, target_dir: Path, name: str, client_id: str) -> Path:
    safe_name = re_sub_non_alnum(str(name or "omnimem-oauth-broker").strip().lower(), "-").strip("-") or "omnimem-oauth-broker"
    txt = (
        f'name = "{safe_name}"\n'
        'main = "cloudflare-worker.js"\n'
        'compatibility_date = "2026-01-01"\n\n'
        "[vars]\n"
        f'GITHUB_OAUTH_CLIENT_ID = "{str(client_id or "").strip()}"\n'
    )
    fp = target_dir / "wrangler.toml"
    fp.write_text(txt, encoding="utf-8")
    return fp

def re_sub_non_alnum(text: str, repl: str = "-") -> str:
    out = []
    last_dash = False
    for ch in text:
        ok = ("a" <= ch <= "z") or ("0" <= ch <= "9")
        if ok:
            out.append(ch)
            last_dash = False
        else:
            if not last_dash:
                out.append(repl)
            last_dash = True
    return "".join(out)

def _run_ext_cmd(cmd: list[str], cwd: Path) -> dict[str, object]:
    try:
        cp = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
        return {
            "ok": bool(cp.returncode == 0),
            "cmd": cmd,
            "exit_code": int(cp.returncode),
            "stdout": (cp.stdout or "")[-2000:],
            "stderr": (cp.stderr or "")[-2000:],
        }
    except Exception as exc:
        return {"ok": False, "cmd": cmd, "exit_code": -1, "error": str(exc)}

def _extract_https_urls(text: str) -> list[str]:
    if not str(text or "").strip():
        return []
    urls: list[str] = []
    for m in re.finditer(r"https://[^\s\"'<>]+", text):
        raw = str(m.group(0) or "").strip()
        url = raw.rstrip(".,);:!?")
        if url:
            urls.append(url)
    return urls

def _detect_broker_url_from_deploy_output(provider: str, deploy_out: dict[str, object]) -> str:
    p = str(provider or "").strip().lower()
    txt = "\n".join(
        [
            str(deploy_out.get("stdout", "") or ""),
            str(deploy_out.get("stderr", "") or ""),
        ]
    )
    urls = _extract_https_urls(txt)
    if not urls:
        return ""

    if p == "cloudflare":
        preferred = [u for u in urls if ".workers.dev" in u]
    elif p == "vercel":
        preferred = [u for u in urls if ".vercel.app" in u]
    elif p == "railway":
        preferred = [u for u in urls if ".railway.app" in u]
    elif p == "fly":
        preferred = [u for u in urls if ".fly.dev" in u]
    else:
        preferred = []
    if preferred:
        return preferred[0]
    return urls[0]

def _oauth_broker_init_action(
    *,
    provider: str,
    target_dir: Path,
    name: str,
    client_id: str,
    force: bool,
) -> dict[str, object]:
    template_dir = _oauth_broker_template_dir(provider)
    if not template_dir.exists():
        return {"ok": False, "error": f"template not found: {template_dir}"}
    if target_dir.exists() and any(target_dir.iterdir()) and not bool(force):
        return {"ok": False, "error": f"target is not empty: {target_dir}", "hint": "use --force to overwrite"}

    target_dir.mkdir(parents=True, exist_ok=True)
    if bool(force):
        for p in target_dir.iterdir():
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)

    shutil.copytree(template_dir, target_dir, dirs_exist_ok=True)
    generated: list[str] = []
    if provider == "cloudflare":
        fp = _write_cloudflare_wrangler_toml(
            target_dir=target_dir,
            name=name,
            client_id=client_id,
        )
        generated.append(str(fp))
    return {
        "ok": True,
        "action": "init",
        "provider": provider,
        "template": str(template_dir),
        "target_dir": str(target_dir),
        "generated": generated,
        "next": _oauth_broker_deploy_hint(provider, target_dir),
        "note": "Auth-only broker: memory sync data does not go through this service.",
    }

def _oauth_broker_deploy_action(
    *,
    provider: str,
    target_dir: Path,
    name: str,
    client_id: str,
    apply: bool,
) -> dict[str, object]:
    if not target_dir.exists():
        return {"ok": False, "error": f"target dir not found: {target_dir}", "hint": "run init first"}

    hint = _oauth_broker_deploy_hint(provider, target_dir)
    if not bool(apply):
        return {
            "ok": True,
            "action": "deploy-preview",
            "provider": provider,
            "target_dir": str(target_dir),
            "commands": hint,
            "apply": False,
        }

    if provider == "cloudflare":
        if not shutil.which("wrangler"):
            return {"ok": False, "error": "wrangler not found in PATH", "hint": "npm i -g wrangler"}
        if str(client_id or "").strip():
            _write_cloudflare_wrangler_toml(target_dir=target_dir, name=name, client_id=client_id)
        out = _run_ext_cmd(["wrangler", "deploy"], target_dir)
    elif provider == "vercel":
        if not shutil.which("vercel"):
            return {"ok": False, "error": "vercel not found in PATH", "hint": "npm i -g vercel"}
        out = _run_ext_cmd(["vercel", "deploy", "--prod", "--yes"], target_dir)
    elif provider == "railway":
        if not shutil.which("railway"):
            return {"ok": False, "error": "railway not found in PATH", "hint": "npm i -g @railway/cli"}
        out = _run_ext_cmd(["railway", "up"], target_dir)
    elif provider == "fly":
        if not shutil.which("flyctl"):
            return {"ok": False, "error": "flyctl not found in PATH", "hint": "brew install flyctl"}
        out = _run_ext_cmd(["flyctl", "deploy"], target_dir)
    else:
        out = {"ok": False, "error": f"unsupported provider: {provider}"}
    return {"ok": bool(out.get("ok")), "action": "deploy", "provider": provider, "target_dir": str(target_dir), **out}

def _oauth_broker_recommend_provider() -> str:
    for p, bin_name in [("cloudflare", "wrangler"), ("vercel", "vercel"), ("railway", "railway"), ("fly", "flyctl")]:
        if shutil.which(bin_name):
            return p
    return "cloudflare"

def _run_status_cmd(cmd: list[str], timeout_s: float = 8.0) -> dict[str, object]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout_s)
        return {
            "ok": bool(cp.returncode == 0),
            "exit_code": int(cp.returncode),
            "stdout": (cp.stdout or "")[-1200:],
            "stderr": (cp.stderr or "")[-1200:],
        }
    except Exception as exc:
        return {"ok": False, "exit_code": -1, "error": str(exc), "stdout": "", "stderr": ""}


def _oauth_broker_doctor_data(*, cfg_path: Path | None, client_id: str = "") -> dict[str, object]:
    cfg, resolved_cfg_path = load_config_with_path(cfg_path)
    cfg_client_id = str(cfg.get("sync", {}).get("github", {}).get("oauth", {}).get("client_id", "") or "").strip()
    env_client_id = str(os.environ.get("OMNIMEM_GITHUB_OAUTH_CLIENT_ID", "")).strip()
    effective_client_id = str(client_id or "").strip() or env_client_id or cfg_client_id

    providers: list[dict[str, object]] = []
    table = [
        ("cloudflare", "wrangler", ["wrangler", "whoami"], "wrangler login"),
        ("vercel", "vercel", ["vercel", "whoami"], "vercel login"),
        ("railway", "railway", ["railway", "whoami"], "railway login"),
        ("fly", "flyctl", ["flyctl", "auth", "whoami"], "flyctl auth login"),
    ]
    for provider, bin_name, whoami_cmd, login_hint in table:
        installed = bool(shutil.which(bin_name))
        status: dict[str, object] = {"ok": False, "exit_code": -1, "stdout": "", "stderr": ""}
        logged_in = False
        if installed:
            status = _run_status_cmd(whoami_cmd)
            logged_in = bool(status.get("ok", False))
        providers.append(
            {
                "provider": provider,
                "binary": bin_name,
                "installed": installed,
                "logged_in": logged_in,
                "login_hint": login_hint,
                "status": status,
                "template_exists": bool(_oauth_broker_template_dir(provider).exists()),
            }
        )

    preferred = ""
    for p in providers:
        if bool(p.get("installed")) and bool(p.get("logged_in")):
            preferred = str(p.get("provider"))
            break
    if not preferred:
        for p in providers:
            if bool(p.get("installed")):
                preferred = str(p.get("provider"))
                break
    if not preferred:
        preferred = "cloudflare"

    issues: list[str] = []
    actions: list[str] = []
    if not effective_client_id:
        issues.append("missing GitHub OAuth client id")
        actions.append("set OMNIMEM_GITHUB_OAUTH_CLIENT_ID or provide --client-id")
    installed_any = any(bool(p.get("installed")) for p in providers)
    if not installed_any:
        issues.append("no provider CLI found in PATH")
        actions.append("install one provider CLI (wrangler/vercel/railway/flyctl)")
    logged_any = any(bool(p.get("logged_in")) for p in providers if bool(p.get("installed")))
    if installed_any and not logged_any:
        issues.append("no provider is authenticated")
        for p in providers:
            if bool(p.get("installed")):
                actions.append(str(p.get("login_hint")))
    return {
        "ok": True,
        "config_path": str(resolved_cfg_path),
        "oauth_client_id_available": bool(effective_client_id),
        "oauth_client_id_source": "arg" if bool(str(client_id or "").strip()) else ("env" if bool(env_client_id) else ("config" if bool(cfg_client_id) else "none")),
        "recommended_provider": preferred,
        "providers": providers,
        "issues": issues,
        "actions": actions,
        "note": "auth-only broker; memory sync data path remains local",
    }
