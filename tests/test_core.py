import asyncio
from backend.app.imap.otp import extract_otp_code
from backend.app.auth import (
    create_magic_link_token, verify_magic_link_token,
    encrypt_secret, decrypt_secret,
    hash_password, verify_password
)
from backend.app.database import init_db, get_db

def test_otp_extraction():
    cases = [
        ("您的验证码是 482910，5分钟内有效", "482910"),
        ("【GitHub】Your verification code is 918234", "918234"),
        ("Use 384729 to log in to your account", "384729"),
        ("安全确认码：G-928172 请勿泄漏", "G-928172"),
        ("动态密码：8392 为本次登录验证码", "8392"),
        ("这是普通的打折促销邮件，没有代码", None)
    ]
    for text, expected in cases:
        res = extract_otp_code("Notification", text)
        assert res == expected, f"Failed for '{text}': got '{res}', expected '{expected}'"
    print("✅ OTP extraction tests passed!")

def test_magic_link():
    token = create_magic_link_token(100, expire_minutes=10)
    assert verify_magic_link_token(100, token) is True
    # 错误 ID 应失败
    assert verify_magic_link_token(101, token) is False
    # 伪造签名应失败
    fake_token = token[:-4] + "xxxx"
    assert verify_magic_link_token(100, fake_token) is False
    print("✅ Magic Link security tests passed!")

def test_crypto():
    raw_secret = "mypassword123!@#"
    enc = encrypt_secret(raw_secret)
    assert enc != raw_secret
    dec = decrypt_secret(enc)
    assert dec == raw_secret

    pw = "AdminPassword2026"
    h = hash_password(pw)
    assert verify_password(pw, h) is True
    assert verify_password("wrong", h) is False
    print("✅ Cryptographic tests passed!")

async def test_db():
    await init_db()
    async with get_db() as db:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in await cursor.fetchall()]
        assert "users" in tables
        assert "accounts" in tables
        assert "emails" in tables
        assert "emails_fts" in tables
    print("✅ SQLite & FTS5 database tests passed!")

if __name__ == "__main__":
    test_otp_extraction()
    test_magic_link()
    test_crypto()
    asyncio.run(test_db())
