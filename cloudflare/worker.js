// sqlstepper.psbhr.com -> the Cloud Run service. Passes on the visitor's IP for the per-visitor limit.
const ORIGIN = "sqlstepper-70559819464.us-central1.run.app";

export default {
  fetch(req) {
    const url = new URL(req.url);
    url.hostname = ORIGIN;
    const headers = new Headers(req.headers);
    headers.delete("host");
    headers.set("X-Forwarded-For", req.headers.get("CF-Connecting-IP") || "");
    return fetch(url, { method: req.method, headers, body: req.body, redirect: "manual" });
  },
};
