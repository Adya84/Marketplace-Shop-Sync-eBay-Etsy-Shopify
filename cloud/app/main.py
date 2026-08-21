from __future__ import annotations

import html
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .db import SessionLocal, init_db
from .marketplace_oauth import BrokerClient, decode_result
from .models import MarketplaceConnection, Membership, SyncJob, User, Workspace
from .security import decrypt_json, encrypt_json, hash_password, new_csrf, verify_password

settings = get_settings()
broker = BrokerClient(settings.oauth_broker_url)

APP_LOGO = "https://raw.githubusercontent.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/main/marketplace_bridge/logo.png"
MARKET_LOGOS = {
    "shopify": "https://cdn.simpleicons.org/shopify/95BF47",
    "etsy": "https://cdn.simpleicons.org/etsy/F1641E",
    "ebay": "https://cdn.simpleicons.org/ebay/E53238",
}
MARKET_LABELS = {"shopify": "Shopify", "etsy": "Etsy", "ebay": "eBay"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Shop Sync Cloud", version="0.2.0-alpha", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="shopsync_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.secure_cookies,
)


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = new_csrf()
        request.session["csrf"] = token
    return str(token)


def verify_csrf(request: Request, token: str) -> None:
    expected = str(request.session.get("csrf") or "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(400, "Form expired. Refresh the page and try again.")


def current_context(request: Request):
    user_id = request.session.get("user_id")
    workspace_id = request.session.get("workspace_id")
    if not user_id or not workspace_id:
        return None
    with SessionLocal() as db:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == str(user_id),
                Membership.workspace_id == str(workspace_id),
            )
        )
        if not membership:
            request.session.clear()
            return None
        user = db.get(User, str(user_id))
        workspace = db.get(Workspace, str(workspace_id))
        if not user or not workspace:
            request.session.clear()
            return None
        return {"user": user, "workspace": workspace, "role": membership.role}


def require_context(request: Request):
    context = current_context(request)
    if not context:
        raise HTTPException(401, "Sign in to Shop Sync.")
    return context


def brand() -> str:
    return f'''<div class="brand"><img class="app-logo" src="{APP_LOGO}" alt="Shop Sync logo"><div><h1>Shop Sync</h1><div class="muted">One catalogue. Every marketplace.</div></div></div>'''


def shell(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Shop Sync</title><link rel="icon" href="{APP_LOGO}"><style>
:root{{--bg:#06101c;--panel:#0b1727;--line:#22364f;--text:#f6f9fc;--muted:#8da5bf;--blue:#5cc0ff;--blue2:#7b8cff;--green:#39d6a0;--red:#ff718d;--shadow:0 24px 80px rgba(0,0,0,.34)}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 16% 0,#11365f 0,transparent 30%),radial-gradient(circle at 90% 5%,#172d55 0,transparent 28%),var(--bg);color:var(--text);font:15px Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:var(--blue)}}.wrap{{max-width:1240px;margin:auto;padding:28px}}.top{{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:25px}}.brand{{display:flex;align-items:center;gap:14px}}.app-logo{{width:62px;height:62px;object-fit:contain;border-radius:16px;filter:drop-shadow(0 12px 28px rgba(0,0,0,.3))}}h1{{font-size:31px;margin:0;letter-spacing:-.8px}}h2{{margin:0 0 10px;font-size:20px}}p{{color:var(--muted);line-height:1.55}}.card{{background:linear-gradient(180deg,rgba(17,34,55,.96),rgba(10,23,39,.97));border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:var(--shadow)}}.hero{{padding:25px;margin-bottom:18px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(275px,1fr));gap:16px}}.market{{position:relative;overflow:hidden;min-height:225px}}.market::after{{content:"";position:absolute;width:150px;height:150px;border-radius:50%;right:-58px;top:-65px;background:rgba(255,255,255,.035)}}.market-head{{display:flex;align-items:center;justify-content:space-between;gap:14px}}.market-name{{display:flex;align-items:center;gap:12px}}.market-logo{{width:44px;height:44px;object-fit:contain;background:#fff;border-radius:12px;padding:7px}}.row{{display:flex;align-items:center;justify-content:space-between;gap:14px}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}}.btn,button{{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:11px;background:linear-gradient(135deg,var(--blue),var(--blue2));color:#06111d;font-weight:850;padding:11px 15px;text-decoration:none;cursor:pointer}}.btn.secondary,button.secondary{{background:#142941;color:var(--text);border:1px solid var(--line)}}.btn.danger,button.danger{{background:#361b2a;color:#ffd5de;border:1px solid #623049}}.badge{{display:inline-flex;align-items:center;background:#081725;border:1px solid var(--line);border-radius:999px;padding:7px 10px;color:#b9cde1;font-size:12px}}.dot{{width:9px;height:9px;border-radius:50%;background:var(--red);display:inline-block;margin-right:7px}}.dot.ok{{background:var(--green)}}.eyebrow{{font-size:11px;letter-spacing:1.8px;color:#7fcaff;font-weight:900}}.muted{{color:var(--muted)}}.auth{{max-width:500px;margin:6vh auto}}label{{display:block;color:#bdd0e6;font-size:13px;font-weight:750;margin:14px 0 6px}}input,textarea{{width:100%;border:1px solid var(--line);background:#071521;color:var(--text);padding:13px 14px;border-radius:11px;outline:none}}textarea{{min-height:110px;resize:vertical}}input:focus,textarea:focus{{border-color:var(--blue);box-shadow:0 0 0 3px rgba(92,192,255,.12)}}.full{{width:100%;margin-top:18px}}.notice{{padding:12px 14px;border-radius:11px;margin:13px 0}}.error{{background:#3b1a28;color:#ffc7d4;border:1px solid #6d2d45}}.success{{background:#123b31;color:#bdffe8;border:1px solid #236e59}}.nav{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}}.nav a{{text-decoration:none;color:#c7d8e9;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:#0a1827}}.jobs{{width:100%;border-collapse:collapse}}.jobs th,.jobs td{{padding:10px;text-align:left;border-top:1px solid var(--line);font-size:13px}}.jobs th{{color:#93a9c0}}.footer{{text-align:center;color:var(--muted);padding:28px 0 8px;font-size:12px}}@media(max-width:680px){{.wrap{{padding:17px}}.top{{align-items:flex-start;flex-direction:column}}.row{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><div class="wrap">{body}<div class="footer">Shop Sync Cloud · Hosted marketplace sync</div></div></body></html>''')


def auth_page(mode: str, request: Request, error: str = "") -> HTMLResponse:
    signup = mode == "signup"
    heading = "Create your Shop Sync account" if signup else "Welcome back"
    submit = "Create account" if signup else "Sign in"
    switch = 'Already have an account? <a href="/login">Sign in</a>' if signup else 'New to Shop Sync? <a href="/signup">Create an account</a>'
    name = '<label>Workspace / business name</label><input name="workspace_name" maxlength="160" placeholder="My Store" required>' if signup else ""
    error_html = f'<div class="notice error">{esc(error)}</div>' if error else ""
    return shell(heading, f'''<div class="auth">{brand()}<div class="card" style="margin-top:22px"><span class="eyebrow">SHOP SYNC CLOUD</span><h2 style="margin-top:8px">{heading}</h2><p>Connect Shopify, Etsy and eBay from one hosted Shop Sync workspace.</p>{error_html}<form method="post"><input type="hidden" name="csrf_token" value="{csrf(request)}">{name}<label>Email</label><input type="email" name="email" autocomplete="email" required><label>Password</label><input type="password" name="password" minlength="10" autocomplete="{'new-password' if signup else 'current-password'}" required><button class="full">{submit}</button></form><p style="text-align:center;margin-bottom:0">{switch}</p></div></div>''')


def connection_for(workspace_id: str, provider: str):
    with SessionLocal() as db:
        return db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == workspace_id, MarketplaceConnection.provider == provider))


def save_connection(workspace_id: str, provider: str, account_label: str, credentials: dict):
    with SessionLocal() as db:
        item = db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == workspace_id, MarketplaceConnection.provider == provider))
        if not item:
            item = MarketplaceConnection(workspace_id=workspace_id, provider=provider)
            db.add(item)
        item.account_label = account_label[:255]
        item.encrypted_credentials = encrypt_json(credentials)
        item.status = "connected"
        db.commit()


def connect_page(provider: str, request: Request, error: str = "", success: str = "") -> HTMLResponse:
    context = require_context(request)
    if provider not in MARKET_LABELS:
        raise HTTPException(404)
    label = MARKET_LABELS[provider]
    item = connection_for(context["workspace"].id, provider)
    connected = bool(item and item.status == "connected")
    shop_field = '<label>Permanent Shopify store domain</label><input name="shop_domain" placeholder="your-store.myshopify.com" required>' if provider == "shopify" else ""
    error_html = f'<div class="notice error">{esc(error)}</div>' if error else ""
    success_html = f'<div class="notice success">{esc(success)}</div>' if success else ""
    disconnect_form = ""
    if connected:
        disconnect_form = f'''<form method="post" action="/connect/{provider}/disconnect" style="margin-top:18px"><input type="hidden" name="csrf_token" value="{csrf(request)}"><button class="danger">Disconnect {label}</button></form>'''
    return shell(f"Connect {label}", f'''<div class="top">{brand()}<a class="btn secondary" href="/dashboard">← Dashboard</a></div><section class="card" style="max-width:760px;margin:auto"><div class="market-name"><img class="market-logo" src="{MARKET_LOGOS[provider]}" alt="{label} logo"><div><span class="eyebrow">{esc(provider.upper())}</span><h2>Connect {label}</h2></div></div><p>Status: <span class="badge"><i class="dot {'ok' if connected else ''}"></i>{'Connected' if connected else 'Not connected'}</span></p>{success_html}{error_html}<form method="post" action="/connect/{provider}/start"><input type="hidden" name="csrf_token" value="{csrf(request)}">{shop_field}<button>Open {label} sign-in</button></form><p class="muted">After approving access, the Shop Sync broker displays a one-time authorization result. Copy it, return here and paste it below. Your marketplace password is never given to Shop Sync.</p><form method="post" action="/connect/{provider}/finish"><input type="hidden" name="csrf_token" value="{csrf(request)}"><label>Authorization result</label><textarea name="authorization_result" placeholder="Paste the one-time result here" required></textarea><button>Finish {label} connection</button></form>{disconnect_form}</section>''')


@app.get("/health")
def health():
    return {"status": "ok", "service": "shop-sync-cloud", "version": app.version}


@app.get("/")
def index(request: Request):
    return RedirectResponse("/dashboard" if current_context(request) else "/login", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if current_context(request):
        return RedirectResponse("/dashboard", status_code=303)
    return auth_page("signup", request)


@app.post("/signup", response_class=HTMLResponse)
def signup(request: Request, email: str = Form(...), password: str = Form(...), workspace_name: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    try:
        clean_email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    except ValidationError:
        return auth_page("signup", request, "Enter a valid email address.")
    if len(password) < 10:
        return auth_page("signup", request, "Password must be at least 10 characters.")
    workspace_name = workspace_name.strip()[:160]
    if not workspace_name:
        return auth_page("signup", request, "Enter a workspace or business name.")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == clean_email)):
            return auth_page("signup", request, "An account with that email already exists.")
        user = User(email=clean_email, password_hash=hash_password(password))
        workspace = Workspace(name=workspace_name)
        db.add_all([user, workspace])
        db.flush()
        db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
        db.commit()
        request.session.clear()
        request.session.update({"user_id": user.id, "workspace_id": workspace.id, "csrf": new_csrf()})
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_context(request):
        return RedirectResponse("/dashboard", status_code=303)
    return auth_page("login", request)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not verify_password(user.password_hash, password):
            return auth_page("login", request, "Email or password is incorrect.")
        membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
        if not membership:
            return auth_page("login", request, "This account does not have a Shop Sync workspace.")
        request.session.clear()
        request.session.update({"user_id": user.id, "workspace_id": membership.workspace_id, "csrf": new_csrf()})
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/connect/{provider}", response_class=HTMLResponse)
def connection_page(provider: str, request: Request):
    return connect_page(provider, request)


@app.post("/connect/{provider}/start")
async def connection_start(provider: str, request: Request, csrf_token: str = Form(...), shop_domain: str = Form("")):
    verify_csrf(request, csrf_token)
    require_context(request)
    if provider not in MARKET_LABELS:
        raise HTTPException(404)
    shop = shop_domain.strip().lower().removeprefix("https://").rstrip("/")
    if provider == "shopify":
        if not shop.endswith(".myshopify.com"):
            return connect_page(provider, request, "Use the permanent Shopify domain ending in .myshopify.com.")
        request.session["oauth_shopify_shop"] = shop
    state = secrets.token_urlsafe(32)
    request.session[f"oauth_{provider}_state"] = state
    try:
        url = await broker.start(provider, state, shop=shop)
    except Exception as exc:
        return connect_page(provider, request, str(exc))
    return RedirectResponse(url, status_code=303)


@app.post("/connect/{provider}/finish", response_class=HTMLResponse)
async def connection_finish(provider: str, request: Request, authorization_result: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    context = require_context(request)
    if provider not in MARKET_LABELS:
        raise HTTPException(404)
    try:
        decoded = decode_result(authorization_result)
        expected = str(request.session.get(f"oauth_{provider}_state") or "")
        returned = str(decoded.get("state") or "")
        if not expected or not returned or not secrets.compare_digest(expected, returned):
            raise ValueError("Authorization state did not match. Start the connection again.")
        shop = str(request.session.get("oauth_shopify_shop") or "") if provider == "shopify" else ""
        credentials = await broker.exchange(provider, authorization_result, shop=shop)
        account_label = f"{MARKET_LABELS[provider]} account"
        if provider == "shopify":
            credentials["shop_domain"] = str(credentials.get("shop") or shop)
            account_label = credentials["shop_domain"]
        elif provider == "etsy":
            token = str(credentials.get("access_token") or "")
            user_id = token.split(".", 1)[0]
            if user_id.isdigit():
                shop_payload = await broker.etsy_get(credentials, f"/v3/application/users/{user_id}/shops")
                shop = shop_payload if shop_payload.get("shop_id") else ((shop_payload.get("results") or [{}])[0])
                if shop.get("shop_id"):
                    credentials["shop_id"] = str(shop["shop_id"])
                    account_label = str(shop.get("shop_name") or credentials["shop_id"])
        save_connection(context["workspace"].id, provider, account_label, credentials)
        request.session.pop(f"oauth_{provider}_state", None)
        if provider == "shopify":
            request.session.pop("oauth_shopify_shop", None)
        return connect_page(provider, request, success=f"{MARKET_LABELS[provider]} connected successfully.")
    except Exception as exc:
        return connect_page(provider, request, error=str(exc))


@app.post("/connect/{provider}/disconnect")
def connection_disconnect(provider: str, request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    context = require_context(request)
    if provider not in MARKET_LABELS:
        raise HTTPException(404)
    with SessionLocal() as db:
        item = db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == context["workspace"].id, MarketplaceConnection.provider == provider))
        if item:
            item.status = "disconnected"
            item.encrypted_credentials = ""
            item.account_label = ""
            db.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    context = current_context(request)
    if not context:
        return RedirectResponse("/login", status_code=303)
    workspace = context["workspace"]
    user = context["user"]
    with SessionLocal() as db:
        connections = {item.provider: item for item in db.scalars(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == workspace.id)).all()}
        jobs = db.scalars(select(SyncJob).where(SyncJob.workspace_id == workspace.id).order_by(SyncJob.created_at.desc()).limit(8)).all()
    cards = []
    for provider in ("shopify", "etsy", "ebay"):
        label = MARKET_LABELS[provider]
        item = connections.get(provider)
        connected = bool(item and item.status == "connected")
        status = "Connected" if connected else "Not connected"
        account = esc(item.account_label) if item and item.account_label else "Connect your seller/store account to Shop Sync."
        ready = '<span class="badge">Ready for sync</span>' if connected else ''
        cards.append(f'''<section class="card market"><div class="market-head"><div class="market-name"><img class="market-logo" src="{MARKET_LOGOS[provider]}" alt="{label} logo"><div><span class="eyebrow">{esc(provider.upper())}</span><h2>{label}</h2></div></div><span class="badge"><i class="dot {'ok' if connected else ''}"></i>{status}</span></div><p>{account}</p><div class="actions"><a class="btn {'secondary' if connected else ''}" href="/connect/{provider}">{'Manage' if connected else 'Connect'}</a>{ready}</div></section>''')
    job_rows = "".join(f"<tr><td>{esc(job.kind.replace('_',' ').title())}</td><td>{esc(job.status)}</td><td>{esc(job.progress)}</td><td>{esc(job.message)}</td></tr>" for job in jobs) or '<tr><td colspan="4" class="muted">No sync jobs yet.</td></tr>'
    return shell("Dashboard", f'''<div class="top">{brand()}<div class="row"><span class="badge">{esc(user.email)}</span><form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{csrf(request)}"><button class="secondary">Sign out</button></form></div></div><div class="nav"><a href="/dashboard">Dashboard</a><a href="#marketplaces">Marketplaces</a><a href="#activity">Activity</a></div><section class="card hero"><span class="eyebrow">CLOUD WORKSPACE</span><div class="row"><div><h2 style="font-size:27px;margin-top:7px">One catalogue. Every marketplace.</h2><p style="margin-bottom:0">Hosted Shop Sync for {esc(workspace.name)}. Marketplace credentials are encrypted and isolated to this workspace.</p></div><span class="badge">Owner</span></div></section><div id="marketplaces" class="grid">{''.join(cards)}</div><section id="activity" class="card" style="margin-top:18px"><div class="row"><div><span class="eyebrow">ACTIVITY</span><h2 style="margin-top:7px">Sync jobs</h2></div><span class="badge">Workspace isolated</span></div><table class="jobs"><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{job_rows}</tbody></table></section>''')
