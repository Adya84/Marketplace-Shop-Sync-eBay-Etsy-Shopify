const EBAY_SCOPES = [
  "https://api.ebay.com/oauth/api_scope",
  "https://api.ebay.com/oauth/api_scope/sell.inventory",
];
const ETSY_SCOPES = ["listings_r", "listings_w", "shops_r"];

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "GET,POST,OPTIONS",
    },
  });
}

function b64url(bytes) {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromB64url(value) {
  value = value.replace(/-/g, "+").replace(/_/g, "/");
  value += "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(value);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}

async function hmac(secret, text) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  return b64url(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(text)));
}

async function signedResult(env, payload) {
  const encoded = b64url(new TextEncoder().encode(JSON.stringify(payload)));
  return `${encoded}.${await hmac(env.BROKER_SIGNING_SECRET, encoded)}`;
}

async function verifySignedResult(env, value, provider) {
  const parts = String(value || "").trim().split(".");
  if (parts.length !== 2) throw new Error("Invalid authorization result");
  const [payloadPart, signature] = parts;
  const expected = await hmac(env.BROKER_SIGNING_SECRET, payloadPart);
  if (signature !== expected) throw new Error("Invalid authorization result");
  const payload = JSON.parse(new TextDecoder().decode(fromB64url(payloadPart)));
  if (!payload.code || !payload.state) throw new Error("Authorization result is missing required values");
  if (payload.provider && payload.provider !== provider) throw new Error("Authorization result is for the wrong marketplace");
  if (Date.now() / 1000 - Number(payload.iat || 0) > 900) throw new Error("Authorization result has expired");
  return payload;
}

async function sha256Challenge(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return b64url(digest);
}

function randomVerifier() {
  return b64url(crypto.getRandomValues(new Uint8Array(64)));
}

function htmlEscape(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function callbackPage(provider, result) {
  const name = provider === "etsy" ? "Etsy" : "eBay";
  return new Response(`<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shop Sync ${name} approved</title>
<style>body{font-family:system-ui,sans-serif;max-width:680px;margin:50px auto;padding:20px}button{font-size:18px;padding:14px 20px;cursor:pointer}code{word-break:break-all}</style></head>
<body><h1>${name} approved</h1><p>Your ${name} account has approved Shop Sync.</p><p>Copy the authorization result, then return to Shop Sync.</p>
<button id="copy">Copy authorization result</button><p id="status"></p>
<script>const value=${JSON.stringify(result)};document.getElementById("copy").onclick=async()=>{try{await navigator.clipboard.writeText(value);document.getElementById("status").textContent="Copied. Return to Shop Sync, paste it into Authorization result, then finish the connection."}catch(e){document.getElementById("status").textContent="Clipboard access was blocked. Copy the authorization result manually."}};</script>
<noscript><code>${htmlEscape(result)}</code></noscript></body></html>`, {
    headers: { "content-type": "text/html;charset=UTF-8" },
  });
}

function declinedPage(provider, message) {
  const name = provider === "etsy" ? "Etsy" : "eBay";
  return new Response(`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>${name} connection declined</title></head><body><h1>${name} connection declined</h1><p>${htmlEscape(message)}</p><p>You can close this tab and return to Shop Sync.</p></body></html>`, {
    status: 400,
    headers: { "content-type": "text/html;charset=UTF-8" },
  });
}

function ebayHosts(environment) {
  return environment === "sandbox"
    ? { auth: "https://auth.sandbox.ebay.com", api: "https://api.sandbox.ebay.com" }
    : { auth: "https://auth.ebay.com", api: "https://api.ebay.com" };
}

function ebayBasicAuth(env) {
  return `Basic ${btoa(`${env.EBAY_CLIENT_ID}:${env.EBAY_CLIENT_SECRET}`)}`;
}

async function ebayRefreshKey(env, refreshToken) {
  return await hmac(env.BROKER_SIGNING_SECRET, `refresh:${refreshToken}`);
}

async function etsyRefreshKey(env, refreshToken) {
  return await hmac(env.BROKER_SIGNING_SECRET, `etsy-refresh:${refreshToken}`);
}

function ebayConfigured(env) {
  return Boolean(env.EBAY_CLIENT_ID && env.EBAY_CLIENT_SECRET && env.EBAY_RUNAME && env.BROKER_SIGNING_SECRET);
}

function etsyConfigured(env) {
  return Boolean(env.ETSY_KEYSTRING && env.ETSY_SHARED_SECRET && env.ETSY_REDIRECT_URI && env.BROKER_SIGNING_SECRET);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET,POST,OPTIONS" } });

    if (url.pathname === "/health") {
      return json({ status: "ok", configured: ebayConfigured(env), ebay_configured: ebayConfigured(env), etsy_configured: etsyConfigured(env) });
    }

    // ----- eBay OAuth -----
    if (url.pathname === "/api/ebay/oauth/start" && request.method === "POST") {
      if (!ebayConfigured(env)) return json({ detail: "Shop Sync eBay OAuth broker is not configured" }, 503);
      const body = await request.json();
      const state = String(body.state || "").trim();
      if (!state) return json({ detail: "Missing OAuth state" }, 400);
      const hosts = ebayHosts(body.environment || "production");
      const params = new URLSearchParams({ client_id: env.EBAY_CLIENT_ID, response_type: "code", redirect_uri: env.EBAY_RUNAME, scope: EBAY_SCOPES.join(" "), state, prompt: "login" });
      return json({ authorization_url: `${hosts.auth}/oauth2/authorize?${params.toString()}` });
    }

    if (url.pathname === "/api/ebay/oauth/callback" && request.method === "GET") {
      const error = url.searchParams.get("error");
      if (error) return declinedPage("ebay", url.searchParams.get("error_description") || error);
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      if (!code || !state) return declinedPage("ebay", "The authorization code or state is missing.");
      return callbackPage("ebay", await signedResult(env, { provider: "ebay", code, state, iat: Math.floor(Date.now() / 1000) }));
    }

    if (url.pathname === "/api/ebay/oauth/exchange" && request.method === "POST") {
      try {
        if (!ebayConfigured(env)) throw new Error("Shop Sync eBay OAuth broker is not configured");
        const body = await request.json();
        const payload = await verifySignedResult(env, body.authorization_result, "ebay");
        const hosts = ebayHosts(body.environment || "production");
        const form = new URLSearchParams({ grant_type: "authorization_code", code: payload.code, redirect_uri: env.EBAY_RUNAME });
        const response = await fetch(`${hosts.api}/identity/v1/oauth2/token`, { method: "POST", headers: { Authorization: ebayBasicAuth(env), "Content-Type": "application/x-www-form-urlencoded" }, body: form });
        if (!response.ok) return json({ detail: "eBay rejected the authorization code exchange" }, 502);
        const token = await response.json();
        const refreshToken = token.refresh_token || "";
        return json({ access_token: token.access_token, refresh_token: refreshToken, refresh_key: refreshToken ? await ebayRefreshKey(env, refreshToken) : "", expires_in: token.expires_in || 7200, refresh_token_expires_in: token.refresh_token_expires_in || 0, scopes: EBAY_SCOPES });
      } catch (error) { return json({ detail: error.message }, 400); }
    }

    if (url.pathname === "/api/ebay/oauth/refresh" && request.method === "POST") {
      try {
        const body = await request.json();
        if (!body.refresh_token || body.refresh_key !== await ebayRefreshKey(env, body.refresh_token)) return json({ detail: "Invalid Shop Sync refresh credential" }, 401);
        const hosts = ebayHosts(body.environment || "production");
        const form = new URLSearchParams({ grant_type: "refresh_token", refresh_token: body.refresh_token, scope: (body.scopes || EBAY_SCOPES).join(" ") });
        const response = await fetch(`${hosts.api}/identity/v1/oauth2/token`, { method: "POST", headers: { Authorization: ebayBasicAuth(env), "Content-Type": "application/x-www-form-urlencoded" }, body: form });
        if (!response.ok) return json({ detail: "eBay rejected the refresh token request" }, 502);
        const token = await response.json();
        const refreshToken = token.refresh_token || body.refresh_token;
        return json({ access_token: token.access_token, refresh_token: refreshToken, refresh_key: await ebayRefreshKey(env, refreshToken), expires_in: token.expires_in || 7200 });
      } catch (error) { return json({ detail: error.message }, 400); }
    }

    // ----- Etsy OAuth -----
    if (url.pathname === "/api/etsy/oauth/start" && request.method === "POST") {
      try {
        if (!etsyConfigured(env)) return json({ detail: "Shop Sync Etsy OAuth broker is not configured" }, 503);
        const body = await request.json();
        const state = String(body.state || "").trim();
        if (!state) return json({ detail: "Missing OAuth state" }, 400);
        const verifier = randomVerifier();
        const challenge = await sha256Challenge(verifier);
        const params = new URLSearchParams({ response_type: "code", client_id: env.ETSY_KEYSTRING, redirect_uri: env.ETSY_REDIRECT_URI, scope: ETSY_SCOPES.join(" "), state, code_challenge: challenge, code_challenge_method: "S256" });
        return json({ authorization_url: `https://www.etsy.com/oauth/connect?${params.toString()}`, code_verifier: verifier });
      } catch (error) { return json({ detail: error.message }, 400); }
    }

    if (url.pathname === "/api/etsy/oauth/callback" && request.method === "GET") {
      const error = url.searchParams.get("error");
      if (error) return declinedPage("etsy", url.searchParams.get("error_description") || error);
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      if (!code || !state) return declinedPage("etsy", "The authorization code or state is missing.");
      return callbackPage("etsy", await signedResult(env, { provider: "etsy", code, state, iat: Math.floor(Date.now() / 1000) }));
    }

    if (url.pathname === "/api/etsy/oauth/exchange" && request.method === "POST") {
      try {
        if (!etsyConfigured(env)) return json({ detail: "Shop Sync Etsy OAuth broker is not configured" }, 503);
        const body = await request.json();
        const payload = await verifySignedResult(env, body.authorization_result, "etsy");
        if (!body.code_verifier) return json({ detail: "Missing Etsy PKCE verifier" }, 400);
        const form = new URLSearchParams({ grant_type: "authorization_code", client_id: env.ETSY_KEYSTRING, redirect_uri: env.ETSY_REDIRECT_URI, code: payload.code, code_verifier: body.code_verifier });
        const response = await fetch("https://api.etsy.com/v3/public/oauth/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form });
        if (!response.ok) return json({ detail: "Etsy rejected the authorization code exchange" }, 502);
        const token = await response.json();
        const refreshToken = token.refresh_token || "";
        return json({ access_token: token.access_token, refresh_token: refreshToken, refresh_key: refreshToken ? await etsyRefreshKey(env, refreshToken) : "", expires_in: token.expires_in || 3600, scopes: ETSY_SCOPES });
      } catch (error) { return json({ detail: error.message }, 400); }
    }

    if (url.pathname === "/api/etsy/oauth/refresh" && request.method === "POST") {
      try {
        if (!etsyConfigured(env)) return json({ detail: "Shop Sync Etsy OAuth broker is not configured" }, 503);
        const body = await request.json();
        if (!body.refresh_token || body.refresh_key !== await etsyRefreshKey(env, body.refresh_token)) return json({ detail: "Invalid Shop Sync Etsy refresh credential" }, 401);
        const form = new URLSearchParams({ grant_type: "refresh_token", client_id: env.ETSY_KEYSTRING, refresh_token: body.refresh_token });
        const response = await fetch("https://api.etsy.com/v3/public/oauth/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form });
        if (!response.ok) return json({ detail: "Etsy rejected the refresh token request" }, 502);
        const token = await response.json();
        const refreshToken = token.refresh_token || body.refresh_token;
        return json({ access_token: token.access_token, refresh_token: refreshToken, refresh_key: await etsyRefreshKey(env, refreshToken), expires_in: token.expires_in || 3600 });
      } catch (error) { return json({ detail: error.message }, 400); }
    }

    if (url.pathname === "/api/etsy/proxy/get" && request.method === "POST") {
      try {
        if (!etsyConfigured(env)) return json({ detail: "Shop Sync Etsy OAuth broker is not configured" }, 503);
        const body = await request.json();
        const path = String(body.path || "");
        if (!path.startsWith("/v3/application/") || path.includes("..")) return json({ detail: "Invalid Etsy API path" }, 400);
        if (!body.access_token) return json({ detail: "Missing Etsy access token" }, 401);
        const target = new URL(`https://api.etsy.com${path}`);
        for (const [key, value] of Object.entries(body.params || {})) target.searchParams.set(key, String(value));
        const response = await fetch(target.toString(), { headers: { "x-api-key": `${env.ETSY_KEYSTRING}:${env.ETSY_SHARED_SECRET}`, Authorization: `Bearer ${body.access_token}` } });
        const text = await response.text();
        return new Response(text, { status: response.status, headers: { "content-type": response.headers.get("content-type") || "application/json", "access-control-allow-origin": "*" } });
      } catch (error) { return json({ detail: error.message }, 400); }
    }

    return json({ detail: "Not found" }, 404);
  },
};
