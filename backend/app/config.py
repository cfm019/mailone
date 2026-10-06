import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # 基础配置
    BASE_DIR: Path = BASE_DIR
    APP_NAME: str = "MailOne"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "127.0.0.1"
    PORT: int = 11001
    
    # 外部公网访问域名（用于在 Telegram 推送里生成免密 Magic Link 查看地址）
    # 例如：https://mail.yourdomain.com
    BASE_URL: str = Field(default="http://localhost:11001", env="BASE_URL")

    # 安全密钥（若未设置，会自动从安全文件读取或生成并持久化）
    SECRET_KEY: str = Field(default="", env="SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 72
    MAGIC_LINK_EXPIRE_MINUTES: int = 30  # Telegram 临时查看链接有效期

    # 存储路径
    DATA_DIR: Path = BASE_DIR / "data"
    DB_PATH: Path = BASE_DIR / "data" / "db.sqlite"
    STORAGE_DIR: Path = BASE_DIR / "data" / "storage"

    # Telegram Bot 推送配置
    TELEGRAM_BOT_TOKEN: str = Field(default="", env="TELEGRAM_BOT_TOKEN")
    # 允许接收推送的 Chat ID（多个逗号分隔，如 "12345678,98765432"）
    TELEGRAM_ALLOWED_CHAT_IDS: str = Field(default="", env="TELEGRAM_ALLOWED_CHAT_IDS")
    # Telegram API 反代地址（国内服务器可选填，例如 https://api.telegram.org）
    TELEGRAM_API_BASE: str = Field(default="https://api.telegram.org", env="TELEGRAM_API_BASE")

    # IMAP 同步引擎设置
    POLL_INTERVAL_SECONDS: int = 60  # IDLE 断开或不支持 IDLE 时的轮询兜底周期
    MAX_CONCURRENT_SYNCS: int = 5
    SYNC_DELETE_REMOTE_DEFAULT: bool = False # 默认删除时不直接干掉远程，保护原邮箱

    def init_directories_and_secrets(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        
        # 确保持久化一个稳定的 SECRET_KEY
        secret_file = self.DATA_DIR / ".secret_key"
        if not self.SECRET_KEY:
            if secret_file.exists():
                self.SECRET_KEY = secret_file.read_text(encoding="utf-8").strip()
            else:
                generated = secrets.token_urlsafe(48)
                secret_file.write_text(generated, encoding="utf-8")
                self.SECRET_KEY = generated

    @property
    def telegram_chat_ids_list(self) -> list[int]:
        if not self.TELEGRAM_ALLOWED_CHAT_IDS:
            return []
        ids = []
        for x in self.TELEGRAM_ALLOWED_CHAT_IDS.split(","):
            x = x.strip()
            if x:
                try:
                    ids.append(int(x))
                except ValueError:
                    pass
        return ids

settings = Settings()
settings.init_directories_and_secrets()
