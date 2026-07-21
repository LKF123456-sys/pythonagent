"""认证集成测试：注册 / 登录 / 刷新 / 登出 / 黑名单 / 限流 / 禁用账号。"""

import uuid

import pytest


def _uname() -> str:
    return f"u_{uuid.uuid4().hex[:10]}"


async def _register(client, username: str, password: str = "secret123"):
    return await client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )


async def _login(client, username: str, password: str = "secret123"):
    return await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


# ============================================================
# 注册
# ============================================================

class TestRegister:
    async def test_register_success(self, client):
        resp = await _register(client, _uname())
        assert resp.status_code == 201
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["token_type"] == "bearer"
        assert data["user_id"] > 0
        assert data["is_admin"] is False

    async def test_register_duplicate_username(self, client):
        name = _uname()
        assert (await _register(client, name)).status_code == 201
        dup = await _register(client, name)
        assert dup.status_code == 409

    async def test_register_weak_password_rejected(self, client):
        resp = await _register(client, _uname(), password="123")  # < 6 位
        assert resp.status_code == 422

    async def test_register_short_username_rejected(self, client):
        resp = await _register(client, "a", password="secret123")  # < 2 字符
        assert resp.status_code == 422


# ============================================================
# 登录
# ============================================================

class TestLogin:
    async def test_login_success(self, client):
        name = _uname()
        await _register(client, name)
        resp = await _login(client, name)
        assert resp.status_code == 200
        assert resp.json()["access_token"]

    async def test_login_wrong_password(self, client):
        name = _uname()
        await _register(client, name)
        resp = await _login(client, name, password="wrongpass")
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client):
        resp = await _login(client, "no_such_user_xyz")
        assert resp.status_code == 401

    async def test_disabled_user_cannot_login(self, client, app):
        """被禁用的账号登录应返回 401。"""
        from app.db.connection import get_pool

        name = _uname()
        await _register(client, name)
        pool = get_pool()
        await pool.execute("UPDATE users SET is_active = 0 WHERE username = ?", (name,))

        resp = await _login(client, name)
        assert resp.status_code == 401
        assert "禁用" in resp.json()["detail"]


# ============================================================
# 当前用户
# ============================================================

class TestMe:
    async def test_me_returns_user_info(self, client, auth_tokens):
        headers = {"Authorization": f"Bearer {auth_tokens['access_token']}"}
        resp = await client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == auth_tokens["username"]
        assert data["user_id"] == auth_tokens["user_id"]

    async def test_me_without_token(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code in (401, 403)

    async def test_me_with_invalid_token(self, client):
        resp = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer not.a.valid.token"}
        )
        assert resp.status_code == 401


# ============================================================
# Refresh Token 轮换
# ============================================================

class TestRefresh:
    async def test_refresh_returns_new_tokens(self, client, auth_tokens):
        resp = await client.post(
            "/api/auth/refresh", json={"refresh_token": auth_tokens["refresh_token"]}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"] != auth_tokens["refresh_token"]  # 轮换

    async def test_refresh_reuse_old_token_fails(self, client, auth_tokens):
        """旧 refresh token 轮换后应失效（防重放）。"""
        old_refresh = auth_tokens["refresh_token"]
        first = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert first.status_code == 200
        # 再次使用旧 token 应被拒绝
        second = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert second.status_code == 401

    async def test_refresh_with_access_token_fails(self, client, auth_tokens):
        """用 access token 调用 refresh 应被拒绝（类型校验）。"""
        resp = await client.post(
            "/api/auth/refresh", json={"refresh_token": auth_tokens["access_token"]}
        )
        assert resp.status_code == 401

    async def test_refresh_with_garbage_fails(self, client):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
        assert resp.status_code == 401


# ============================================================
# 登出与黑名单
# ============================================================

class TestLogout:
    async def test_logout_blacklists_access_token(self, client, auth_tokens):
        """登出后 access token 应被拉黑，无法再访问受保护端点。"""
        headers = {"Authorization": f"Bearer {auth_tokens['access_token']}"}
        # 登出前可访问
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
        # 登出
        logout = await client.post("/api/auth/logout", headers=headers)
        assert logout.status_code == 204
        # 登出后同一 token 失效
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 401

    async def test_logout_revokes_refresh_token(self, client, auth_tokens):
        """登出时携带 refresh token 应一并撤销。"""
        headers = {"Authorization": f"Bearer {auth_tokens['access_token']}"}
        logout = await client.post(
            "/api/auth/logout",
            headers=headers,
            json={"refresh_token": auth_tokens["refresh_token"]},
        )
        assert logout.status_code == 204
        # refresh token 已撤销
        resp = await client.post(
            "/api/auth/refresh", json={"refresh_token": auth_tokens["refresh_token"]}
        )
        assert resp.status_code == 401


# ============================================================
# 请求频率限制
# ============================================================

class TestRateLimit:
    async def test_register_rate_limited(self, client, app):
        """注册端点限制 3 次/分钟，第 4 次应返回 429。"""
        from app.core.rate_limit import limiter

        limiter.enabled = True
        try:
            codes = []
            for _ in range(4):
                resp = await _register(client, _uname())
                codes.append(resp.status_code)
            assert codes[:3] == [201, 201, 201]
            assert codes[3] == 429
        finally:
            limiter.enabled = False

    async def test_login_rate_limited(self, client, app):
        """登录端点限制 5 次/分钟，第 6 次应返回 429。"""
        from app.core.rate_limit import limiter

        limiter.enabled = True
        try:
            codes = []
            for _ in range(6):
                resp = await _login(client, "rate_limit_probe", password="whatever")
                codes.append(resp.status_code)
            # 前 5 次为 401（用户不存在），第 6 次触发限流 429
            assert codes[5] == 429
        finally:
            limiter.enabled = False
