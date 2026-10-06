import asyncio
import httpx
from backend.app.main import app

async def run_api_tests():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 检查健康
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"
        print("✅ /api/health passed")

        # 2. 检查管理员状态
        res = await client.get("/api/auth/status")
        assert res.status_code == 200
        has_admin = res.json()["has_admin"]
        print(f"✅ /api/auth/status passed (has_admin={has_admin})")

        # 3. 初始化管理员
        if not has_admin:
            res = await client.post("/api/auth/init-admin", json={"username": "admin", "password": "Password123!"})
            assert res.status_code == 200
            token = res.json()["access_token"]
            print("✅ /api/auth/init-admin passed")
        else:
            res = await client.post("/api/auth/login", json={"username": "admin", "password": "Password123!"})
            assert res.status_code == 200
            token = res.json()["access_token"]
            print("✅ /api/auth/login passed")

        headers = {"Authorization": f"Bearer {token}"}

        # 4. 获取 me
        res = await client.get("/api/auth/me", headers=headers)
        assert res.status_code == 200
        assert res.json()["username"] == "admin"
        print("✅ /api/auth/me passed")

        # 5. 获取账户列表
        res = await client.get("/api/accounts", headers=headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)
        print("✅ /api/accounts list passed")

        # 6. 获取邮件列表
        res = await client.get("/api/mails", headers=headers)
        assert res.status_code == 200
        assert "items" in res.json()
        print("✅ /api/mails list passed")

        # 7. 静态页面加载
        res = await client.get("/")
        assert res.status_code == 200
        assert "MailOne" in res.text
        print("✅ Frontend index.html served")

    print("\n🎉 All End-to-End API tests passed!")

if __name__ == "__main__":
    asyncio.run(run_api_tests())
