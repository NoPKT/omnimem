export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST") return json({ ok: false, error: "method not allowed" }, 405);
    const body = await readJson(request);
    if (!body.ok) return json({ ok: false, error: "invalid json" }, 400);
    const data = body.value;

    if (url.pathname === "/v1/github/device/start") {
      const clientId = str(data.client_id) || str(env.GITHUB_OAUTH_CLIENT_ID);
      if (!clientId) return json({ ok: false, error: "missing client_id" }, 400);
      const scope = str(data.scope) || "repo";
      const form = new URLSearchParams({ client_id: clientId, scope });
      const r = await fetch("https://github.com/login/device/code", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "omnimem-oauth-broker" },
        body: form.toString(),
      });
      const j = await safeJson(r);
      if (!r.ok) return json({ ok: false, error: j.error_description || j.error || "github start failed" }, r.status);
      return json({
        ok: true,
        device_code: str(j.device_code),
        user_code: str(j.user_code),
        verification_uri: str(j.verification_uri),
        verification_uri_complete: str(j.verification_uri_complete),
        interval: num(j.interval, 5),
        expires_in: num(j.expires_in, 900),
        client_id: clientId,
      });
    }

    if (url.pathname === "/v1/github/device/poll") {
      const clientId = str(data.client_id) || str(env.GITHUB_OAUTH_CLIENT_ID);
      const deviceCode = str(data.device_code);
      if (!clientId || !deviceCode) return json({ ok: false, error: "missing client_id/device_code" }, 400);
      const form = new URLSearchParams({
        client_id: clientId,
        device_code: deviceCode,
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
      });
      const r = await fetch("https://github.com/login/oauth/access_token", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "omnimem-oauth-broker" },
        body: form.toString(),
      });
      const j = await safeJson(r);
      if (!r.ok) return json({ ok: false, error: j.error_description || j.error || "github poll failed" }, r.status);
      if (!str(j.access_token)) {
        const err = str(j.error) || "authorization_pending";
        if (err === "authorization_pending" || err === "slow_down") {
          return json({ ok: true, pending: true, error: err, retry_after: err === "slow_down" ? 7 : 5 });
        }
        return json({ ok: false, error: str(j.error_description) || err }, 400);
      }
      return json({
        ok: true,
        access_token: str(j.access_token),
        token_type: str(j.token_type) || "bearer",
        scope: str(j.scope),
      });
    }

    return json({ ok: false, error: "not found" }, 404);
  },
};

async function readJson(request) {
  try {
    return { ok: true, value: await request.json() };
  } catch {
    return { ok: false, value: {} };
  }
}

async function safeJson(resp) {
  try {
    return await resp.json();
  } catch {
    return {};
  }
}

function str(v) {
  return (typeof v === "string" ? v : "").trim();
}

function num(v, d) {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
