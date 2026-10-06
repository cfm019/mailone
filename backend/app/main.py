import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.database import init_db
from backend.app.imap.worker import sync_manager
from backend.app.api.auth_router import router as auth_router
from backend.app.api.account_router import router as account_router
from backend.app.api.mail_router import router as mail_router
from backend.app.api.magic_router import router as magic_router
from backend.app.api.telegram_router import router as telegram_router
from backend.app.telegram.bot import telegram_notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mailone.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动前初始化
    logger.info("Initializing MailOne database and directories...")
    settings.init_directories_and_secrets()
    await init_db()
    # 启动 IMAP 同步监听协程
    await sync_manager.start()
    # 启动 Telegram 机器人指令监听
    await telegram_notifier.start_polling()
    yield
    # 关机清理
    logger.info("Shutting down IMAP sync manager and Telegram listener...")
    await telegram_notifier.stop_polling()
    await sync_manager.stop()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# 允许跨域（方便反代或独立前端）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(mail_router)
app.include_router(magic_router)
app.include_router(telegram_router)

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "telegram_configured": telegram_notifier.is_configured
    }

# 挂载前端静态文件
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")

    @app.get("/")
    async def serve_index():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/login")
    async def serve_login():
        return FileResponse(FRONTEND_DIR / "login.html")

    @app.get("/view")
    @app.get("/view.html")
    async def serve_magic_view():
        return FileResponse(FRONTEND_DIR / "view.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
