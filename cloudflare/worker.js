// sqlstepper.psbhr.com -> the Cloud Run service. Passes on the visitor's real IP for the per-visitor
// limits, plus a secret (npx wrangler secret put PROXY_SECRET) that proves the request came through here.
const ORIGIN = "sqlstepper-70559819464.us-central1.run.app";

export default {
  fetch(req, env) {
    const url = new URL(req.url);
    url.hostname = ORIGIN;
    const headers = new Headers(req.headers);
    headers.delete("host");
    headers.set("X-Forwarded-For", req.headers.get("CF-Connecting-IP") || "");
    headers.set("X-Proxy-Secret", env.PROXY_SECRET || "");
    return fetch(url, { method: req.method, headers, body: req.body, redirect: "manual" });
  },
};
