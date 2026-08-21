from __future__ import annotations

import html
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .db import SessionLocal, init_db
from .models import MarketplaceConnection, Membership, User, Workspace
from .security import hash_password, new_csrf, verify_password

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Shop Sync Cloud", version="0.1.0-alpha", lifespan=lifespan)
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
    if not expected or token != expected:
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


def shell(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Shop Sync</title><style>
:root{{--bg:#07111f;--card:#0e1c2d;--card2:#13243a;--line:#233852;--text:#f5f8fc;--muted:#8fa6c2;--blue:#57b7ff;--green:#37d39a;--red:#ff7590;--shadow:0 24px 70px rgba(0,0,0,.32)}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#12345c 0,transparent 30%),radial-gradient(circle at 90% 10%,#162c50 0,transparent 26%),var(--bg);color:var(--text);font:15px Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}a{{color:var(--blue)}}.wrap{{max-width:1180px;margin:auto;padding:28px}}.top{{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:28px}}.brand{{display:flex;align-items:center;gap:13px}}.brandmark{{width:46px;height:46px;border-radius:14px;background:linear-gradient(135deg,#6ec6ff,#6d7dff);display:grid;place-items:center;font-weight:900;font-size:21px;color:#06101c;box-shadow:0 10px 35px rgba(87,183,255,.25)}}h1{{font-size:31px;margin:0;letter-spacing:-.8px}}h2{{margin:0 0 10px;font-size:20px}}p{{color:var(--muted);line-height:1.55}}.card{{background:linear-gradient(180deg,rgba(19,36,58,.94),rgba(12,25,42,.96));border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:var(--shadow)}}.auth{{max-width:470px;margin:7vh auto}}label{{display:block;color:#bdd0e6;font-size:13px;font-weight:700;margin:14px 0 6px}}input{{width:100%;border:1px solid var(--line);background:#091522;color:var(--text);padding:13px 14px;border-radius:11px;outline:none}}input:focus{{border-color:var(--blue);box-shadow:0 0 0 3px rgba(87,183,255,.12)}}button,.btn{{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:11px;background:linear-gradient(135deg,#68c4ff,#6c8cff);color:#06111d;font-weight:850;padding:12px 16px;text-decoration:none;cursor:pointer}}button.secondary,.btn.secondary{{background:#162a42;color:var(--text);border:1px solid var(--line)}}.full{{width:100%;margin-top:18px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:16px}}.market{{position:relative;overflow:hidden}}.market::after{{content:"";position:absolute;width:130px;height:130px;border-radius:50%;right:-45px;top:-55px;background:rgba(255,255,255,.035)}}.row{{display:flex;justify-content:space-between;align-items:center;gap:14px}}.dot{{width:9px;height:9px;border-radius:50%;background:var(--red);display:inline-block;margin-right:7px}}.dot.ok{{background:var(--green)}}.badge{{display:inline-flex;align-items:center;background:#0a1827;border:1px solid var(--line);border-radius:999px;padding:7px 10px;color:#bdd0e6;font-size:12px}}.hero{{padding:26px;margin-bottom:18px}}.eyebrow{{font-size:11px;letter-spacing:1.8px;color:#7ec8ff;font-weight:900}}.muted{{color:var(--muted)}}.error{{background:#3d1b29;color:#ffc4d2;border:1px solid #6d2b43;padding:11px 13px;border-radius:10px;margin:12px 0}}.footer{{text-align:center;color:var(--muted);padding:28px 0 8px;font-size:12px}}@media(max-width:650px){{.wrap{{padding:18px}}.top{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><div class="wrap">{body}<div class="footer">Shop Sync Cloud · Public beta foundation</div></div></body></html>''')


def auth_page(mode: str, request: Request, error: str = "") -> HTMLResponse:
    signup = mode == "signup"
    heading = "Create your Shop Sync account" if signup else "Welcome back"
    submit = "Create account" if signup else "Sign in"
    switch = 'Already have an account? <a href="login">Sign in</a>' if signup else 'New to Shop Sync? <a href="signup">Create an account</a>'
    name = '<label>Workspace / business name</label><input name="workspace_name" maxlength="160" placeholder="My Store" required>' if signup else ""
    error_html = f'<div class="error">{esc(error)}</div>' if error else ""
    return shell(heading, f'''<div class="auth"><div class="brand"><div class="brandmark">S</div><div><h1>Shop Sync</h1><div class="muted">One catalogue. Every marketplace.</div></div></div><div class="card" style="margin-top:22px"><span class="eyebrow">SHOP SYNC CLOUD</span><h2 style="margin-top:8px">{heading}</h2><p>Connect and manage Shopify, Etsy and eBay without installing Home Assistant.</p>{error_html}<form method="post"><input type="hidden" name="csrf_token" value="{csrf(request)}">{name}<label>Email</label><input type="email" name="email" autocomplete="email" required><label>Password</label><input type="password" name="password" minlength="10" autocomplete="{'new-password' if signup else 'current-password'}" required><button class="full">{submit}</button></form><p style="text-align:center;margin-bottom:0">{switch}</p></div></div>''')


@app.get("/health")
def health():
    return {"status": "ok", "service": "shop-sync-cloud", "version": app.version}


@app.get("/")
def index(request: Request):
    return RedirectResponse("dashboard" if current_context(request) else "login", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if current_context(request):
        return RedirectResponse("dashboard", status_code=303)
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
    return RedirectResponse("dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_context(request):
        return RedirectResponse("dashboard", status_code=303)
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
    return RedirectResponse("dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    context = current_context(request)
    if not context:
        return RedirectResponse("login", status_code=303)
    workspace = context["workspace"]
    user = context["user"]
    with SessionLocal() as db:
        connections = {
            item.provider: item
            for item in db.scalars(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == workspace.id)).all()
        }
    cards = []
    for provider, label in (("shopify", "Shopify"), ("etsy", "Etsy"), ("ebay", "eBay")):
        item = connections.get(provider)
        connected = bool(item and item.status == "connected")
        status = "Connected" if connected else "Not connected"
        action = "Manage" if connected else "Connect"
        cards.append(f'''<section class="card market"><div class="row"><div><span class="eyebrow">{esc(provider.upper())}</span><h2 style="margin-top:8px">{esc(label)}</h2></div><span class="badge"><i class="dot {'ok' if connected else ''}"></i>{status}</span></div><p>{esc(item.account_label) if item and item.account_label else 'Connect your seller/store account to Shop Sync.'}</p><button class="secondary" disabled title="OAuth wiring is the next cloud milestone">{action}</button></section>''')
    return shell("Dashboard", f'''<div class="top"><div class="brand"><div class="brandmark">S</div><div><h1>Shop Sync</h1><div class="muted">{esc(workspace.name)}</div></div></div><div class="row"><span class="badge">{esc(user.email)}</span><form method="post" action="logout"><input type="hidden" name="csrf_token" value="{csrf(request)}"><button class="secondary">Sign out</button></form></div></div><section class="card hero"><span class="eyebrow">CLOUD WORKSPACE</span><div class="row"><div><h2 style="font-size:26px;margin-top:7px">One catalogue. Every marketplace.</h2><p style="margin-bottom:0">Your hosted workspace is ready. Marketplace OAuth connections and product synchronisation plug into this tenant-isolated account.</p></div><span class="badge">Owner</span></div></section><div class="grid">{''.join(cards)}</div>''')
