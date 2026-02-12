export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ ok: false, error: "method not allowed" });
    return;
  }
  const body = typeof req.body === "object" && req.body ? req.body : {};
  const clientId = str(body.client_id) || str(process.env.GITHUB_OAUTH_CLIENT_ID);
  const deviceCode = str(body.device_code);
  if (!clientId || !deviceCode) {
    res.status(400).json({ ok: false, error: "missing client_id/device_code" });
    return;
  }
  const form = new URLSearchParams({
    client_id: clientId,
    device_code: deviceCode,
    grant_type: "urn:ietf:params:oauth:grant-type:device_code",
  });
  const r = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": "omnimem-oauth-broker",
    },
    body: form.toString(),
  });
  const j = await safeJson(r);
  if (!r.ok) {
    res.status(r.status).json({ ok: false, error: j.error_description || j.error || "github poll failed" });
    return;
  }
  if (!str(j.access_token)) {
    const err = str(j.error) || "authorization_pending";
    if (err === "authorization_pending" || err === "slow_down") {
      res.status(200).json({ ok: true, pending: true, error: err, retry_after: err === "slow_down" ? 7 : 5 });
      return;
    }
    res.status(400).json({ ok: false, error: str(j.error_description) || err });
    return;
  }
  res.status(200).json({
    ok: true,
    access_token: str(j.access_token),
    token_type: str(j.token_type) || "bearer",
    scope: str(j.scope),
  });
}

function str(v) {
  return (typeof v === "string" ? v : "").trim();
}
async function safeJson(resp) {
  try {
    return await resp.json();
  } catch {
    return {};
  }
}
