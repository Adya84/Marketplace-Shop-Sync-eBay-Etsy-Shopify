from .main import app
from .sync_routes import router as sync_router

app.include_router(sync_router)
