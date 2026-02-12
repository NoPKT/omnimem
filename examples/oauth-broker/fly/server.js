import http from "node:http";

const PORT = Number(process.env.PORT || 8787);
const CLIENT_ID = String(process.env.GITHUB_OAUTH_CLIENT_ID || "").trim();

const server = http.createServer(async (req, res) => {
  if (req.method !== "POST") return send(res, 405, { ok: false, error: "method not allowed" });
  const body = await readJson(req);
  if (!body.ok) return send(res, 400, { ok: false, error: "invalid json" });
  const data = body.value;

  if (req.url === "/v1/github/device/start") {
    const clientId = str(data.client_id) || CLIENT_ID;
    if (!clientId) return send(res, 400, { ok: false, error: "missing client_id" });
    const scope = str(data.scope) || "repo";
    const r = await postForm("https://github.com/login/device/code", { client_id: clientId, scope });
    if (!r.ok) return send(res, r.status, { ok: false, error: r.error });
    return send(res, 200, {
      ok: true,
      device_code: str(r.json.device_code),
      user_code: str(r.json.user_code),
      verification_uri: str(r.json.verification_uri),
      verification_uri_complete: str(r.json.verification_uri_complete),
      interval: num(r.json.interval, 5),
      expires_in: num(r.json.expires_in, 900),
      client_id: clientId,
    });
  }

  if (req.url === "/v1/github/device/poll") {
    const clientId = str(data.client_id) || CLIENT_ID;
    const deviceCode = str(data.device_code);
    if (!clientId || !deviceCode) return send(res, 400, { ok: false, error: "missing client_id/device_code" });
    const r = await postForm("https://github.com/login/oauth/access_token", {
      client_id: clientId,
      device_code: deviceCode,
      grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    });
    if (!r.ok) return send(res, r.status, { ok: false, error: r.error });
    if (!str(r.json.access_token)) {
      const err = str(r.json.error) || "authorization_pending";
      if (err === "authorization_pending" || err === "slow_down") {
        return send(res, 200, { ok: true, pending: true, error: err, retry_after: err === "slow_down" ? 7 : 5 });
      }
      return send(res, 400, { ok: false, error: str(r.json.error_description) || err });
    }
    return send(res, 200, {
      ok: true,
      access_token: str(r.json.access_token),
      token_type: str(r.json.token_type) || "bearer",
      scope: str(r.json.scope),
    });
  }

  return send(res, 404, { ok: false, error: "not found" });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`omnimem oauth broker listening on ${PORT}`);
});

async function readJson(req) {
  try {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const raw = Buffer.concat(chunks).toString("utf-8");
    return { ok: true, value: raw.trim() ? JSON.parse(raw) : {} };
  } catch {
    return { ok: false, value: {} };
  }
}

async function postForm(url, form) {
  try {
    const data = new URLSearchParams();
    for (const [k, v] of Object.entries(form || {})) data.set(k, String(v || ""));
    const r = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "omnimem-oauth-broker",
      },
      body: data.toString(),
    });
    const j = await safeJson(r);
    if (!r.ok) return { ok: false, status: r.status, json: j, error: j.error_description || j.error || "request failed" };
    return { ok: true, status: r.status, json: j };
  } catch (e) {
    return { ok: false, status: 500, json: {}, error: String(e) };
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

function send(res, code, obj) {
  res.statusCode = code;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}
