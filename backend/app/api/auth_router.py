from fastapi import APIRouter, Depends, HTTPException, status, Response
from pydantic import BaseModel
from typing import Optional

from backend.app.database import get_db
from backend.app.schemas import LoginRequest, LoginResponse, SetupTOTPResponse, VerifyTOTPRequest, DisableTOTPRequest
from backend.app.auth import (
    hash_password, verify_password, create_access_token,
    generate_totp_secret, verify_totp, generate_totp_qr_base64,
    get_current_user
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

class InitAdminRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@router.get("/status")
async def get_system_auth_status():
    """检查系统是否已初始化管理员"""
    async with get_db() as db:
        cursor = await db.execute("SELECT count(*) as count FROM users")
        row = await cursor.fetchone()
        has_admin = row["count"] > 0
    return {"has_admin": has_admin}

@router.post("/init-admin")
async def init_admin(req: InitAdminRequest):
    """初次使用时创建系统管理员账号"""
    async with get_db() as db:
        cursor = await db.execute("SELECT count(*) as count FROM users")
        row = await cursor.fetchone()
        if row["count"] > 0:
            raise HTTPException(status_code=400, detail="管理员已存在，请直接登录")

        pw_hash = hash_password(req.password)
        await db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (req.username, pw_hash)
        )
        await db.commit()

    token = create_access_token({"sub": req.username})
    return {"message": "管理员创建成功", "access_token": token, "username": req.username}

@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response):
    """用户登录（支持 2FA TOTP 双因素认证）"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (req.username,))
        user = await cursor.fetchone()

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    # 检查是否开启了 TOTP
    if user["is_totp_enabled"]:
        if not req.totp_code:
            return LoginResponse(
                access_token="",
                is_totp_required=True,
                username=user["username"]
            )
        if not verify_totp(user["totp_secret"], req.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="两步验证码 (TOTP) 无效或已过期"
            )

    token = create_access_token({"sub": user["username"], "uid": user["id"]})
    # 写入 HttpOnly Cookie
    response.set_cookie(
        key="mailone_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=72 * 3600
    )

    return LoginResponse(
        access_token=token,
        is_totp_required=False,
        username=user["username"]
    )

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="mailone_token")
    return {"message": "已退出登录"}

@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    username = user.get("sub")
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, username, is_totp_enabled, created_at FROM users WHERE username = ?",
            (username,)
        )
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": row["id"],
        "username": row["username"],
        "is_totp_enabled": bool(row["is_totp_enabled"]),
        "totp_enabled": bool(row["is_totp_enabled"]),
        "created_at": row["created_at"]
    }

@router.post("/setup-totp", response_model=SetupTOTPResponse)
async def setup_totp(user: dict = Depends(get_current_user)):
    """生成 TOTP 密钥和二维码供 Authenticator 扫码"""
    username = user.get("sub")
    secret = generate_totp_secret()
    qr_data_url = generate_totp_qr_base64(username, secret)
    return SetupTOTPResponse(secret=secret, qr_code_data_url=qr_data_url, qr_uri=qr_data_url)

@router.post("/verify-totp")
async def verify_and_enable_totp(req: VerifyTOTPRequest, user: dict = Depends(get_current_user)):
    """校验并开启 2FA"""
    username = user.get("sub")
    if not req.secret:
        raise HTTPException(status_code=400, detail="缺少密钥参数")
    clean_code = req.code.strip().replace(" ", "")
    if not verify_totp(req.secret, clean_code):
        raise HTTPException(status_code=400, detail="验证码错误，无法启用 2FA")

    async with get_db() as db:
        await db.execute(
            "UPDATE users SET totp_secret = ?, is_totp_enabled = 1 WHERE username = ?",
            (req.secret, username)
        )
        await db.commit()

    return {"message": "两步验证 (2FA) 启用成功！"}

@router.post("/disable-totp")
async def disable_totp(req: DisableTOTPRequest, user: dict = Depends(get_current_user)):
    """关闭 2FA"""
    username = user.get("sub")
    clean_code = req.code.strip().replace(" ", "")
    async with get_db() as db:
        cursor = await db.execute("SELECT totp_secret FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        if not row or not row["totp_secret"]:
            raise HTTPException(status_code=400, detail="未开启 2FA")

        if not verify_totp(row["totp_secret"], clean_code):
            raise HTTPException(status_code=400, detail="验证码错误，无法关闭 2FA")

        await db.execute(
            "UPDATE users SET totp_secret = NULL, is_totp_enabled = 0 WHERE username = ?",
            (username,)
        )
        await db.commit()

    return {"message": "两步验证 (2FA) 已关闭"}

@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    username = user.get("sub")
    async with get_db() as db:
        cursor = await db.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        if not row or not verify_password(req.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码不正确")

        new_hash = hash_password(req.new_password)
        await db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username))
        await db.commit()

    return {"message": "密码修改成功"}
