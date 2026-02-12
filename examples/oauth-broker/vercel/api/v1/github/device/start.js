export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ ok: false, error: "method not allowed" });
    return;
  }
  const body = typeof req.body === "object" && req.body ? req.body : {};
  const clientId = str(body.client_id) || str(process.env.GITHUB_OAUTH_CLIENT_ID);
  if (!clientId) {
    res.status(400).json({ ok: false, error: "missing client_id" });
    return;
  }
  const scope = str(body.scope) || "repo";
  const form = new URLSearchParams({ client_id: clientId, scope });
  const r = await fetch("https://github.com/login/device/code", {
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
    res.status(r.status).json({ ok: false, error: j.error_description || j.error || "github start failed" });
    return;
  }
  res.status(200).json({
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

function str(v) {
  return (typeof v === "string" ? v : "").trim();
}
function num(v, d) {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}
async function safeJson(resp) {
  try {
    return await resp.json();
  } catch {
    return {};
  }
}
