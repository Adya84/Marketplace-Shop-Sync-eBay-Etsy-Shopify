from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import urlparse

import httpx
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse

from . import main as core
from . import main_v4 as v4
from . import main_v5 as v5
from .etsy_broker import BrokerEtsyClient
from .reverse_sync import EbayInventoryWriter, EtsyDraftWriter, build_reverse_plan, product_skus
from .settings import settings

app = v5.app
app.version = "0.0.31"


def _defaults(provider: str) -> dict:
    encrypted = core.db.get_credential(f"reverse_{provider}_defaults")
    return json.loads(core.secrets.decrypt(encrypted)) if encrypted else {}


def _save_defaults(provider: str, payload: dict) -> None:
    core.save_credentials(f"reverse_{provider}_defaults", payload)


def _all_products() -> list[dict]:
    rows = []
    for item in core.db.list_products():
        product = core.db.get_product(item["source"], item["source_id"])
        if product:
            rows.append(product)
    return rows


def _mapping(source_id: str, destination: str) -> dict | None:
    with core.db.connect() as conn:
        row = conn.execute(
            "SELECT destination_id,payload FROM mappings WHERE source='shopify' AND source_id=? AND destination=?",
            (source_id, destination),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"] or "{}")
    except Exception:
        payload = {}
    return {"source_id": row["destination_id"], "score": 1000, "reason": "confirmed Shop Sync mapping", "payload": payload}


def _image_keys(product: dict) -> set[str]:
    keys = set()
    for image in product.get("images") or []:
        raw = str(image.get("url") or "").strip()
        if not raw:
            continue
        parsed = urlparse(raw)
        keys.add(raw.casefold())
        name = parsed.path.rsplit("/", 1)[-1].split("?", 1)[0].casefold()
        if name:
            keys.add(name)
    return keys


def _add_photo_candidates(plan: dict, product: dict, destination: str) -> None:
    source_images = _image_keys(product)
    if not source_images:
        return
    destination_products = [p for p in _all_products() if p.get("source") == destination]
    for listing in plan["listings"]:
        known = {str(c.get("source_id")) for c in listing.get("existing_candidates", [])}
        for candidate in destination_products:
            overlap = source_images & _image_keys(candidate)
            if not overlap:
                continue
            candidate_id = str(candidate.get("source_id") or "")
            if not candidate_id:
                continue
            if candidate_id in known:
                for row in listing["existing_candidates"]:
                    if str(row.get("source_id")) == candidate_id:
                        row["score"] = int(row.get("score", 0)) + min(30, 10 * len(overlap))
                        row["reason"] += " + matching photo"
                continue
            listing["existing_candidates"].append({
                "source_id": candidate_id,
                "title": candidate.get("title", ""),
                "score": min(55, 35 + 10 * len(overlap)),
                "reason": "matching product photo",
                "matching_skus": [],
            })
        listing["existing_candidates"].sort(key=lambda row: int(row.get("score", 0)), reverse=True)


class ReverseBrokerEtsyClient(BrokerEtsyClient):
    async def request(self, method: str, path: str, *, params=None, form=None, json_data=None):
        if self.refresh_token and (not self.expires_at or time.time() >= self.expires_at - 300):
            await self._refresh()
        payload = {
            "access_token": self.access_token,
            "broker_key": self.broker_key,
            "method": method.upper(),
            "path": path,
            "params": params or {},
            "form": form,
            "json": json_data,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.broker_url}/api/etsy/api/request", json=payload)
            response.raise_for_status()
            return response.json() if response.content else {}


async def _etsy_client() -> ReverseBrokerEtsyClient:
    credential = core.get_credentials("etsy")
    if credential.get("oauth_mode") != "publisher_broker":
        raise HTTPException(400, "Reconnect Etsy with the current Shop Sync OAuth connection before using reverse sync")
    return ReverseBrokerEtsyClient(**credential)


def _ebay_xml(value) -> str:
    return html.escape(str(value or ""), quote=False)


async def _revise_ebay_existing(item_id: str, listing: dict, defaults: dict) -> dict:
    credential = core.get_credentials("ebay")
    credential = await v4.v3.ebay_broker.ensure_access_token(credential, settings.ebay_environment) if hasattr(v4.v3, "ebay_broker") else credential
    core.save_credentials("ebay", credential)
    token = credential["access_token"]
    variants = listing.get("variants") or []
    if not variants:
        raise ValueError("Shopify product has no variants")
    pictures = "".join(f"<PictureURL>{_ebay_xml(i.get('url'))}</PictureURL>" for i in listing.get("images") or [] if i.get("url"))
    variation_xml = ""
    if len(variants) > 1:
        names = listing.get("kept_options") or []
        specifics_set = "".join(
            "<NameValueList><Name>%s</Name><Value>%s</Value></NameValueList>" % (
                _ebay_xml(name), _ebay_xml(value)
            )
            for name in names
            for value in dict.fromkeys(
                next((o.get("value") for o in v.get("options") or [] if o.get("name") == name), "") for v in variants
            ) if value
        )
        rows = []
        for variant in variants:
            specs = "".join(
                f"<NameValueList><Name>{_ebay_xml(o.get('name'))}</Name><Value>{_ebay_xml(o.get('value'))}</Value></NameValueList>"
                for o in variant.get("options") or [] if o.get("name") != "Title"
            )
            rows.append(
                f"<Variation><SKU>{_ebay_xml(variant.get('sku'))}</SKU><StartPrice>{_ebay_xml(variant.get('price'))}</StartPrice>"
                f"<Quantity>{max(0,int(variant.get('quantity') or 0))}</Quantity><VariationSpecifics>{specs}</VariationSpecifics></Variation>"
            )
        variation_xml = f"<Variations>{''.join(rows)}<VariationSpecificsSet>{specifics_set}</VariationSpecificsSet></Variations>"
    else:
        variation_xml = f"<SKU>{_ebay_xml(variants[0].get('sku'))}</SKU><StartPrice>{_ebay_xml(variants[0].get('price'))}</StartPrice><Quantity>{max(0,int(variants[0].get('quantity') or 0))}</Quantity>"
    body = f'''<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents"><Item><ItemID>{_ebay_xml(item_id)}</ItemID>
<Title>{_ebay_xml(listing['title'][:80])}</Title><Description>{_ebay_xml(listing.get('description_html') or listing['title'])}</Description>
<PictureDetails>{pictures}</PictureDetails>{variation_xml}</Item></ReviseFixedPriceItemRequest>'''
    endpoint = "https://api.ebay.com/ws/api.dll" if settings.ebay_environment == "production" else "https://api.sandbox.ebay.com/ws/api.dll"
    headers = {"X-EBAY-API-CALL-NAME":"ReviseFixedPriceItem","X-EBAY-API-COMPATIBILITY-LEVEL":"1423","X-EBAY-API-SITEID":"3","X-EBAY-API-IAF-TOKEN":token,"Content-Type":"text/xml"}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(endpoint, content=body.encode(), headers=headers)
        response.raise_for_status()
    text = response.text
    if "<Ack>Failure</Ack>" in text:
        message = re.search(r"<LongMessage>(.*?)</LongMessage>", text, re.S)
        raise RuntimeError(html.unescape(message.group(1)) if message else "eBay rejected the listing update")
    return {"item_id": item_id, "updated": True}


@app.post("/api/reverse/defaults/{destination}")
async def save_reverse_defaults(destination: str, payload: str = Form(...)):
    if destination not in {"etsy", "ebay"}:
        raise HTTPException(400, "Destination must be Etsy or eBay")
    try:
        values = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Defaults must be valid JSON") from exc
    _save_defaults(destination, values)
    return {"saved": True, "destination": destination}


@app.get("/api/reverse/shopify/{source_id}/{destination}/plan")
async def reverse_plan(source_id: str, destination: str):
    product = core.db.get_product("shopify", source_id)
    if not product:
        raise HTTPException(404, "Shopify product not found; import Shopify first")
    if destination not in {"etsy", "ebay"}:
        raise HTTPException(400, "Destination must be Etsy or eBay")
    plan = build_reverse_plan(product, destination, _defaults(destination), _all_products())
    _add_photo_candidates(plan, product, destination)
    mapped = _mapping(source_id, destination)
    if mapped:
        for listing in plan["listings"]:
            listing["existing_candidates"].insert(0, mapped)
    return plan


@app.post("/api/reverse/shopify/{source_id}/{destination}/export")
async def reverse_export(source_id: str, destination: str, listing_index: int = Form(0), existing_id: str = Form(""), create_new: bool = Form(False)):
    product = core.db.get_product("shopify", source_id)
    if not product:
        raise HTTPException(404, "Shopify product not found")
    defaults = _defaults(destination)
    plan = build_reverse_plan(product, destination, defaults, _all_products())
    _add_photo_candidates(plan, product, destination)
    if plan["missing_defaults"]:
        raise HTTPException(400, "Missing marketplace defaults: " + ", ".join(plan["missing_defaults"]))
    if listing_index < 0 or listing_index >= len(plan["listings"]):
        raise HTTPException(400, "Invalid generated listing")
    listing = plan["listings"][listing_index]
    candidates = listing.get("existing_candidates") or []
    if candidates and not existing_id and not create_new:
        raise HTTPException(409, "Existing listing match found. Choose Update existing or Create new.")
    try:
        if destination == "etsy":
            client = await _etsy_client()
            result = await EtsyDraftWriter(client).create_or_update_draft(listing, defaults, existing_id or None)
            core.save_credentials("etsy", client.credential_payload())
            destination_id = str(result.get("listing_id") or existing_id)
        elif destination == "ebay":
            credential = core.get_credentials("ebay")
            if existing_id:
                result = await _revise_ebay_existing(existing_id, listing, defaults)
                destination_id = existing_id
            else:
                result = await EbayInventoryWriter(credential["access_token"], defaults.get("marketplace_id", "EBAY_GB")).create_draft(listing, defaults)
                destination_id = str(result.get("group_key") or (result.get("offer_ids") or [""])[0])
        else:
            raise HTTPException(400, "Destination must be Etsy or eBay")
    except HTTPException:
        raise
    except Exception as exc:
        core.log.exception("Reverse export failed")
        raise HTTPException(400, str(exc)) from exc
    core.db.save_mapping("shopify", source_id, destination, destination_id, {"result": result, "listing_index": listing_index})
    return {"ok": True, "destination": destination, "destination_id": destination_id, "result": result}


v5._drop_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    response = v5.dashboard()
    page = response.body.decode("utf-8")
    shopify_rows = []
    for row in core.db.list_products():
        if row.get("source") != "shopify":
            continue
        sid = html.escape(str(row["source_id"]), quote=True)
        title = html.escape(str(row["title"]))
        shopify_rows.append(f'''<tr><td>{title}</td><td>{row.get('variant_count',0)}</td><td>{row.get('stock_total',0)}</td><td><button onclick="reversePlan('{sid}','etsy')">Etsy</button> <button onclick="reversePlan('{sid}','ebay')">eBay</button></td></tr>''')
    reverse = f'''<section class="card"><h2>Reverse Sync — Shopify → Etsy / eBay</h2><p>Shopify is the master. Shop Sync adapts titles, descriptions, quantities and variations for each marketplace. Etsy products with more than two option groups are automatically split into separate drafts. Existing listings are checked by confirmed mapping, SKU, title and matching photos before anything is overwritten.</p>
<details><summary>Marketplace defaults</summary><p>Save the required IDs once. These are used only when Shopify does not contain marketplace-specific data.</p>
<form onsubmit="saveDefaults(event,'etsy')"><label>Etsy defaults (JSON)</label><textarea name="payload" rows="5" placeholder='{{"taxonomy_id":"...","shipping_profile_id":"...","readiness_state_id":"..."}}'>{html.escape(json.dumps(_defaults('etsy')))}</textarea><button>Save Etsy defaults</button></form>
<form onsubmit="saveDefaults(event,'ebay')"><label>eBay defaults (JSON)</label><textarea name="payload" rows="6" placeholder='{{"category_id":"...","merchant_location_key":"...","payment_policy_id":"...","return_policy_id":"...","fulfillment_policy_id":"..."}}'>{html.escape(json.dumps(_defaults('ebay')))}</textarea><button>Save eBay defaults</button></form></details>
<table><thead><tr><th>Shopify product</th><th>Variants</th><th>Qty</th><th>Send to</th></tr></thead><tbody>{''.join(shopify_rows) or '<tr><td colspan="4">Import Shopify to load products.</td></tr>'}</tbody></table></section>'''
    marker = "</main>" if "</main>" in page else "</body>"
    page = page.replace(marker, reverse + marker, 1)
    script = r'''<script>
async function saveDefaults(e,d){e.preventDefault();let r=await fetch('api/reverse/defaults/'+d,{method:'POST',body:new FormData(e.currentTarget)});alert(r.ok?'Saved '+d+' defaults':await r.text())}
async function reversePlan(id,d){
 let r=await fetch('api/reverse/shopify/'+encodeURIComponent(id)+'/'+d+'/plan'); if(!r.ok){alert(await r.text());return} let p=await r.json();
 if(p.missing_defaults.length){alert('Set these '+d+' defaults first: '+p.missing_defaults.join(', '));return}
 let msg='Shop Sync will create '+p.listing_count+' '+d+' listing'+(p.listing_count==1?'':'s')+'.'; if(p.split_for_etsy)msg+=' Etsy split is required because this Shopify product has more than two option groups.';
 for(let i=0;i<p.listings.length;i++){
   let l=p.listings[i], c=l.existing_candidates||[], existing='';
   if(c.length){let top=c[0]; let update=confirm(msg+'\n\nLikely existing listing found:\n'+(top.title||top.source_id)+'\nMatch: '+top.reason+' (score '+top.score+')\n\nOK = UPDATE existing\nCancel = choose whether to create new'); if(update)existing=top.source_id; else if(!confirm('Create a NEW '+d+' listing instead?'))return;}
   else if(!confirm(msg+'\n\nNo existing listing match found. Create draft?'))return;
   let fd=new FormData();fd.set('listing_index',i);fd.set('existing_id',existing);fd.set('create_new',existing?'false':'true');
   let out=await fetch('api/reverse/shopify/'+encodeURIComponent(id)+'/'+d+'/export',{method:'POST',body:fd}); if(!out.ok){alert(await out.text());return}
 }
 alert('Reverse sync complete. Refresh Shop Sync after importing '+d+' again to verify the destination listing and quantities.');
}
</script>'''
    page = page.replace("</body>", script + "</body>", 1)
    return HTMLResponse(page)
