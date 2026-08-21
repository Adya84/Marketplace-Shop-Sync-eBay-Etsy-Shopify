from __future__ import annotations

import secrets as token_secrets
import time

import httpx
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse

from . import main as core
from . import main_v2 as v2
from . import main_v3 as v3
from .etsy import EtsyClient as LegacyEtsyClient
from .etsy_broker import EtsyOAuthBroker
from .settings import settings

app = v3.app
app.version = "0.0.29"
etsy_broker = EtsyOAuthBroker(settings.etsy_oauth_broker_url)


def _drop_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()))
    ]


class EtsyClient(LegacyEtsyClient):
    """Compatibility client supporting legacy local credentials and broker OAuth."""

    def __init__(
        self,
        keystring: str = "",
        shared_secret: str = "",
        shop_id: str = "",
        access_token: str = "",
        refresh_token: str = "",
        expires_at: float = 0,
        refresh_key: str = "",
        oauth_mode: str = "",
        broker_url: str = "",
        **_extra,
    ):
        self.oauth_mode = oauth_mode
        self.refresh_key = refresh_key
        self.broker_url = broker_url or settings.etsy_oauth_broker_url
        self._broker = EtsyOAuthBroker(self.broker_url)
        if oauth_mode == "publisher_broker":
            super().__init__("broker", "broker", shop_id or "pending", access_token, refresh_token, expires_at)
        else:
            super().__init__(keystring, shared_secret, shop_id, access_token, refresh_token, expires_at)

    async def _refresh(self):
        if self.oauth_mode != "publisher_broker":
            return await super()._refresh()
        if not self.refresh_token or not self.refresh_key:
            return
        updated = await self._broker.refresh({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "refresh_key": self.refresh_key,
            "expires_at": self.expires_at,
        })
        self.access_token = updated["access_token"]
        self.refresh_token = updated.get("refresh_token", self.refresh_token)
        self.refresh_key = updated.get("refresh_key", self.refresh_key)
        self.expires_at = float(updated.get("expires_at", self.expires_at))

    async def _get(self, path: str, params=None):
        if self.oauth_mode != "publisher_broker":
            return await super()._get(path, params)
        if self.refresh_token and (not self.expires_at or time.time() >= self.expires_at - 300):
            await self._refresh()
        try:
            return await self._broker.get(self.access_token, path, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401 or not self.refresh_token:
                raise
            await self._refresh()
            return await self._broker.get(self.access_token, path, params)

    def credential_payload(self) -> dict:
        if self.oauth_mode != "publisher_broker":
            return super().credential_payload()
        return {
            "shop_id": self.shop_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "refresh_key": self.refresh_key,
            "expires_at": self.expires_at,
            "oauth_mode": "publisher_broker",
            "broker_url": self.broker_url,
        }


core.EtsyClient = EtsyClient


_drop_route("/api/oauth/etsy/start", "POST")
_drop_route("/api/oauth/etsy/finish", "POST")


@app.post("/api/oauth/etsy/start")
async def start_etsy_oauth():
    state = token_secrets.token_urlsafe(32)
    try:
        started = await etsy_broker.start(state)
    except httpx.HTTPStatusError as exc:
        core.log.warning("Etsy OAuth broker start failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Shop Sync could not start Etsy sign-in; check the hosted OAuth service") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc
    core.save_credentials("etsy_oauth", {
        "state": state,
        "code_verifier": started["code_verifier"],
        "created_at": time.time(),
    })
    return {"authorization_url": started["authorization_url"]}


@app.post("/api/oauth/etsy/finish")
async def finish_etsy_oauth(oauth_result: str = Form(...)):
    pending = core.get_credentials("etsy_oauth")
    if time.time() - float(pending.get("created_at", 0)) > 900:
        core.db.delete_credential("etsy_oauth")
        raise HTTPException(400, "Etsy connection expired; select Connect Etsy and start again")
    try:
        result = etsy_broker.parse_authorization_result(oauth_result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not token_secrets.compare_digest(str(result.get("state", "")), str(pending.get("state", ""))):
        raise HTTPException(400, "Etsy authorization state did not match; start the connection again")
    try:
        token = await etsy_broker.exchange(result["authorization_result"], pending["code_verifier"])
        credentials = {
            "shop_id": "pending",
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token", ""),
            "refresh_key": token.get("refresh_key", ""),
            "expires_at": time.time() + int(token.get("expires_in", 3600)),
            "oauth_mode": "publisher_broker",
            "broker_url": settings.etsy_oauth_broker_url,
        }
        client = EtsyClient(**credentials)
        shop = await client.find_authorised_shop()
        client.shop_id = str(shop["shop_id"])
        credentials = client.credential_payload()
    except httpx.HTTPStatusError as exc:
        core.log.warning("Etsy OAuth broker exchange failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Etsy connection failed; select Connect Etsy and try again") from exc
    except (KeyError, RuntimeError, ValueError) as exc:
        core.log.warning("Etsy OAuth connection failed: %s", exc)
        raise HTTPException(400, str(exc)) from exc
    core.save_credentials("etsy", credentials)
    core.db.delete_credential("etsy_oauth")
    return {"connected": True, "shop": shop.get("shop_name", credentials["shop_id"])}


def _upgrade_etsy_panel(page: str) -> str:
    old = '''<form method="post" action="api/oauth/etsy/start" onsubmit="startEtsy(event)"><label>API keystring</label><input name="keystring" type="password" required autocomplete="off"><label>Shared secret</label><input name="shared_secret" type="password" required autocomplete="off"><button>Connect Etsy</button></form>
    <form method="post" action="api/oauth/etsy/finish" onsubmit="connect(event)" class="etsy-finish"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied from the Etsy approval page"><button>Finish Etsy connection</button></form><small>Tokens and Shop ID are created automatically. Never paste them into chat or screenshots.</small>'''
    new = '''<form method="post" action="api/oauth/etsy/start" onsubmit="startEtsy(event)"><button>Connect Etsy</button></form>
    <form method="post" action="api/oauth/etsy/finish" onsubmit="connect(event)" class="etsy-finish"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied after Etsy approval"><button>Finish Etsy connection</button></form><small>No Etsy developer account or API keys are required for normal users. Sign in to Etsy, approve Shop Sync, copy the authorization result and paste it here. Etsy app credentials remain on the hosted Shop Sync OAuth service.</small>'''
    return page.replace(old, new)


def _fix_activity_refresh(page: str) -> str:
    page = page.replace(
        '<button onclick="refreshActivityV28()">Refresh now</button>',
        '<button id="activity-refresh-now" type="button" onclick="refreshActivityManualV29()">Refresh now</button>',
    )
    script = r'''
    <script>
    async function refreshActivityManualV29(){
      const button=document.getElementById('activity-refresh-now');
      if(button){button.disabled=true;button.textContent='Refreshing…'}
      try{
        const response=await fetch(endpoint('api/status')+(endpoint('api/status').includes('?')?'&':'?')+'_='+Date.now(),{cache:'no-store'});
        if(!response.ok)throw new Error(await response.text());
        const data=await response.json();
        activityJobs=Array.isArray(data.jobs)?data.jobs:[];
        activityPage=1;
        renderActivityLive(data.activity||{});
        renderActivityHistory();
        const age=document.getElementById('activity-live-age');
        if(age&&!data.activity?.active)age.textContent='refreshed just now';
      }catch(error){
        console.warn('Manual Activity refresh failed',error);
        const message=document.getElementById('activity-live-message');
        if(message)message.textContent='Activity refresh failed. Automatic refresh will keep trying.';
      }finally{
        if(button){button.disabled=false;button.textContent='Refresh now'}
      }
    }
    </script>
    '''
    return page.replace('</body>', script + '</body>', 1)


_drop_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    products = core.db.list_products()
    jobs = core.db.list_jobs(5000)
    page = v2.render_dashboard(
        products,
        jobs,
        core.db.get_credential("ebay") is not None,
        core.db.get_credential("etsy") is not None,
        core.db.get_credential("shopify") is not None,
        core.db.get_credential("tiktok") is not None,
    )
    page = v3._upgrade_page(page)
    page = _upgrade_etsy_panel(page)
    return HTMLResponse(_fix_activity_refresh(page))
