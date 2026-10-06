import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.auth import get_current_user
from backend.app.telegram.bot import telegram_notifier
from backend.app.database import set_system_setting, update_env_file

logger = logging.getLogger("mailone.telegram_router")

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

class TelegramConfigResponse(BaseModel):
    bot_token: str
    allowed_chat_ids: str
    api_base: str
    is_configured: bool

class TelegramConfigUpdate(BaseModel):
    bot_token: str = Field(default="", description="Telegram Bot Token")
    allowed_chat_ids: str = Field(default="", description="接收通知的 Chat ID，多个逗号分隔")
    api_base: Optional[str] = Field(default="https://api.telegram.org", description="API 反代地址")

class TelegramTestRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    api_base: Optional[str] = None

@router.get("/config", response_model=TelegramConfigResponse)
async def get_telegram_config(user: dict = Depends(get_current_user)):
    """获取当前 Telegram Bot 配置"""
    return TelegramConfigResponse(
        bot_token=settings.TELEGRAM_BOT_TOKEN or "",
        allowed_chat_ids=settings.TELEGRAM_ALLOWED_CHAT_IDS or "",
        api_base=settings.TELEGRAM_API_BASE or "https://api.telegram.org",
        is_configured=telegram_notifier.is_configured
    )

@router.post("/config")
async def save_telegram_config(req: TelegramConfigUpdate, user: dict = Depends(get_current_user)):
    """保存并即时应用 Telegram Bot 配置"""
    token = req.bot_token.strip()
    chat_ids = req.allowed_chat_ids.strip()
    api_base = (req.api_base or "https://api.telegram.org").strip().rstrip("/")
    if not api_base:
        api_base = "https://api.telegram.org"

    # 1. 持久化到 SQLite 数据库
    await set_system_setting("telegram_bot_token", token)
    await set_system_setting("telegram_allowed_chat_ids", chat_ids)
    await set_system_setting("telegram_api_base", api_base)

    # 2. 同步写入 .env 文件
    try:
        update_env_file({
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_ALLOWED_CHAT_IDS": chat_ids,
            "TELEGRAM_API_BASE": api_base
        })
    except Exception as e:
        logger.warning("Failed to sync .env file: %s", e)

    # 3. 动态更新内存与重载 Telegram 协程监听
    await telegram_notifier.reload_config(token, chat_ids, api_base)

    return {
        "success": True,
        "message": "Telegram Bot 配置已保存并即时生效",
        "is_configured": telegram_notifier.is_configured
    }

@router.post("/test")
async def test_telegram_push(req: Optional[TelegramTestRequest] = None, user: dict = Depends(get_current_user)):
    """测试 Telegram Bot 推送"""
    bot_token = req.bot_token.strip() if req and req.bot_token else None
    chat_id = req.chat_id.strip() if req and req.chat_id else None
    api_base = req.api_base.strip() if req and req.api_base else None

    ok, msg = await telegram_notifier.send_test_message(
        bot_token=bot_token,
        chat_id=chat_id,
        api_base=api_base
    )
    return {"success": ok, "message": msg}
