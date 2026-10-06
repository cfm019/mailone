import base64
import hashlib
import hmac
import io
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import pyotp
import qrcode
import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Security, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.app.config import settings

# --- 1. 密码哈希 (Bcrypt) ---

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

# --- 2. 邮箱应用密码 AES/Fernet 对称加解密 ---

def _get_fernet_key() -> bytes:
    # 派生一个合法的 32 字节 base64 Fernet key
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_secret(plain_text: str) -> str:
    """加密邮箱密码等敏感凭据"""
    f = Fernet(_get_fernet_key())
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_secret(encrypted_text: str) -> str:
    """解密敏感凭据"""
    try:
        f = Fernet(_get_fernet_key())
        return f.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""

# --- 3. JWT 访问令牌管理 ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except Exception:
        return None

# --- 4. TOTP 2FA 双因素认证 ---

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)

def generate_totp_qr_base64(username: str, secret: str) -> str:
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name=settings.APP_NAME)
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

# --- 5. Telegram Magic Link 短期只读签名 ---

def create_magic_link_token(mail_id: int, expire_minutes: Optional[int] = None) -> str:
    """为单封邮件生成短期安全的只读 Token"""
    if expire_minutes is None:
        expire_minutes = settings.MAGIC_LINK_EXPIRE_MINUTES
    exp = int(time.time()) + (expire_minutes * 60)
    payload = {
        "scope": "magic_mail_view",
        "mid": mail_id,
        "exp": exp
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    # 计算 HMAC 签名
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:24]
    return f"{encoded}.{signature}"

def verify_magic_link_token(mail_id: int, token: str) -> bool:
    """验证 Magic Link Token 是否合法未过期且属于该邮件"""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return False
        encoded, signature = parts
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()[:24]
        if not hmac.compare_digest(signature, expected_sig):
            return False
        
        payload_data = json.loads(base64.urlsafe_b64decode(encoded.encode("utf-8")).decode("utf-8"))
        if payload_data.get("scope") != "magic_mail_view":
            return False
        if payload_data.get("mid") != mail_id:
            return False
        if time.time() > payload_data.get("exp", 0):
            return False
        return True
    except Exception:
        return False

# --- 6. FastAPI 依赖项注入 ---

security = HTTPBearer(auto_error=False)

async def get_current_user_optional(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Optional[dict]:
    token = None
    if auth and auth.credentials:
        token = auth.credentials
    else:
        # 兼容 Cookie 中的 session_token
        token = request.cookies.get("mailone_token")

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None
    return payload

async def get_current_user(
    current_user: Optional[dict] = Depends(get_current_user_optional)
) -> dict:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
