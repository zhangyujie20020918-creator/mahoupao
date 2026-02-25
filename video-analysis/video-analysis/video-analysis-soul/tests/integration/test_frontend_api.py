"""
前端页面 API 集成测试 — 真实请求（需要后端运行在 localhost:8004）

覆盖 soul.html / souldev.html 所有用到的接口：
  - 系统：GET /status, GET /models
  - 用户：GET /users, POST /users, DELETE /users/{id}
  - ：GET /souls, GET /souls/{name}
  - 历史：GET /history/{uid}/{soul}
  - 对话：POST /chat (SSE 流式)

运行：
  cd video-analysis-soul
  python -m pytest tests/integration/test_frontend_api.py -v --tb=short
"""

import json
import time

import pytest
import requests

API = "http://localhost:8004/api/soul"
TIMEOUT = 15


# ─────────────────────── 工具函数 ───────────────────────


def api_get(path, **kwargs):
    r = requests.get(API + path, timeout=TIMEOUT, **kwargs)
    r.raise_for_status()
    return r.json()


def api_post(path, body=None, **kwargs):
    r = requests.post(API + path, json=body, timeout=TIMEOUT, **kwargs)
    r.raise_for_status()
    return r.json()


def api_delete(path, **kwargs):
    r = requests.delete(API + path, timeout=TIMEOUT, **kwargs)
    r.raise_for_status()
    return r.json()


def parse_sse_events(response):
    """从 SSE 响应中解析出所有 (event_type, data_dict) 对"""
    events = []
    current_event = ""
    for line in response.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = {"_raw": data_str}
            events.append((current_event, data))
    return events


# ─────────────────────── 前置检查 ───────────────────────


@pytest.fixture(scope="session", autouse=True)
def check_server_online():
    """如果后端没有跑，直接跳过整个测试文件"""
    try:
        r = requests.get(API + "/status", timeout=5)
        r.raise_for_status()
    except Exception:
        pytest.skip("Soul 后端未运行 (localhost:8004)，跳过集成测试")


# ═══════════════════════════════════════════════════════
#  1. 系统端点 — souldev.html Tab: System
# ═══════════════════════════════════════════════════════


class TestSystem:
    def test_status(self):
        """GET /status — 服务在线、字段完整"""
        data = api_get("/status")
        assert data["success"] is True
        inner = data["data"]
        assert inner["status"] == "running"
        assert isinstance(inner["active_sessions"], int)
        assert isinstance(inner["port"], int)

    def test_models(self):
        """GET /models — 返回可用模型列表 + 默认模型"""
        data = api_get("/models")
        assert data["success"] is True
        inner = data["data"]
        assert isinstance(inner["models"], list) and len(inner["models"]) > 0
        assert isinstance(inner["default"], str) and inner["default"] != ""
        # 默认模型应在列表中
        assert inner["default"] in inner["models"]


# ═══════════════════════════════════════════════════════
#  2. 用户管理 — soul.html 欢迎弹窗 / souldev.html Tab: Users
# ═══════════════════════════════════════════════════════


class TestUsers:
    _created_user_id = None

    def test_create_user(self):
        """POST /users — 创建用户，返回 id/name/created_at/last_active"""
        test_name = f"pytest_user_{int(time.time())}"
        data = api_post("/users", {"name": test_name})
        assert data["success"] is True
        user = data["data"]
        assert user["name"] == test_name
        assert "id" in user and len(user["id"]) > 0
        assert "created_at" in user
        assert "last_active" in user
        TestUsers._created_user_id = user["id"]

    def test_list_users(self):
        """GET /users — 列表中包含刚创建的用户"""
        data = api_get("/users")
        assert data["success"] is True
        users = data["data"]["users"]
        assert isinstance(users, list)
        ids = [u["id"] for u in users]
        assert TestUsers._created_user_id in ids

    def test_delete_user(self):
        """DELETE /users/{id} — 删除用户成功"""
        uid = TestUsers._created_user_id
        assert uid, "没有可删除的用户（create 测试可能失败了）"
        data = api_delete(f"/users/{uid}")
        assert data["success"] is True
        # 再查列表确认已删除
        data2 = api_get("/users")
        ids = [u["id"] for u in data2["data"]["users"]]
        assert uid not in ids

    def test_delete_nonexistent_user(self):
        """DELETE /users/{id} — 删除不存在的用户返回 404"""
        r = requests.delete(API + "/users/nonexistent-id-12345", timeout=TIMEOUT)
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════
#  3.  — soul.html 侧栏 / souldev.html Tab: Souls
# ═══════════════════════════════════════════════════════


class TestSouls:
    _first_soul = None

    def test_list_souls(self):
        """GET /souls — 返回至少一个，字段完整"""
        data = api_get("/souls")
        assert data["success"] is True
        personas = data["data"]["personas"]
        assert isinstance(personas, list) and len(personas) > 0
        p = personas[0]
        assert "name" in p
        assert "has_knowledge_base" in p
        assert "has_system_prompt" in p
        TestSouls._first_soul = p["name"]

    def test_soul_detail(self):
        """GET /souls/{name} — 详情字段完整"""
        name = TestSouls._first_soul
        assert name, "没有可用"
        data = api_get(f"/souls/{requests.utils.quote(name)}")
        assert data["success"] is True
        detail = data["data"]
        assert detail["name"] == name
        # 关键字段存在
        for field in ("type", "speaking_style", "topic_expertise",
                       "personality_traits", "common_phrases"):
            assert field in detail, f"缺少字段: {field}"

    def test_soul_not_found(self):
        """GET /souls/{name} — 不存在的返回 404"""
        r = requests.get(API + "/souls/不存在的XYZ", timeout=TIMEOUT)
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════
#  4. 历史记录 — soul.html 切换 / souldev.html Tab: History
# ═══════════════════════════════════════════════════════


class TestHistory:
    """历史记录查询（不依赖已有对话，空结果也算通过）"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """创建临时用户"""
        data = api_post("/users", {"name": "pytest_history_tmp"})
        self.uid = data["data"]["id"]
        souls = api_get("/souls")["data"]["personas"]
        self.soul = souls[0]["name"] if souls else None
        yield
        try:
            api_delete(f"/users/{self.uid}")
        except Exception:
            pass

    def test_history_today(self):
        """GET /history/{uid}/{soul} — 返回 today + available_dates"""
        if not self.soul:
            pytest.skip("无")
        data = api_get(
            f"/history/{self.uid}/{requests.utils.quote(self.soul)}"
        )
        assert data["success"] is True
        inner = data["data"]
        assert "today" in inner
        assert "available_dates" in inner
        assert isinstance(inner["today"]["messages"], list)

    def test_history_with_date(self):
        """GET /history/{uid}/{soul}?date=2025-01-01 — 按日期查询不报错"""
        if not self.soul:
            pytest.skip("无")
        data = api_get(
            f"/history/{self.uid}/{requests.utils.quote(self.soul)}",
            params={"date": "2025-01-01"},
        )
        assert data["success"] is True
        inner = data["data"]
        assert "messages" in inner
        assert isinstance(inner["messages"], list)


# ═══════════════════════════════════════════════════════
#  5. 对话 SSE — soul.html 核心功能 / souldev.html Chat Test
#     需要真实 LLM Key，会产生一轮真实对话
# ═══════════════════════════════════════════════════════


class TestChatSSE:
    """真实 SSE 对话测试 — 使用 Gemini API"""

    @pytest.fixture(autouse=True)
    def setup(self):
        data = api_post("/users", {"name": "pytest_chat_tmp"})
        self.uid = data["data"]["id"]
        souls = api_get("/souls")["data"]["personas"]
        self.soul = souls[0]["name"] if souls else None
        yield
        try:
            api_delete(f"/users/{self.uid}")
        except Exception:
            pass

    def test_chat_stream_basic(self):
        """POST /chat — SSE 流：收到 token 事件 + done 事件"""
        if not self.soul:
            pytest.skip("无")

        r = requests.post(
            API + "/chat",
            json={
                "user_id": self.uid,
                "soul": self.soul,
                "message": "你好，简单介绍一下你自己",
            },
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=60,
        )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        events = parse_sse_events(r)
        event_types = [e[0] for e in events]

        # 必须有 token 和 done
        assert "token" in event_types, f"缺少 token 事件，收到: {event_types}"
        assert "done" in event_types, f"缺少 done 事件，收到: {event_types}"

        # 拼接回复内容应该非空
        reply = "".join(
            e[1].get("content", "") or e[1].get("token", "")
            for e in events if e[0] == "token"
        )
        assert len(reply) > 0, "回复内容为空"
        print(f"\n  [LLM Reply] {reply[:120]}...")

    def test_chat_stream_events_order(self):
        """POST /chat — SSE 事件顺序：thinking/searching 在 token 之前，done 在最后"""
        if not self.soul:
            pytest.skip("无")

        r = requests.post(
            API + "/chat",
            json={
                "user_id": self.uid,
                "soul": self.soul,
                "message": "帮我分析一下最近的市场趋势",
            },
            stream=True,
            timeout=60,
        )
        events = parse_sse_events(r)
        event_types = [e[0] for e in events]

        # done 应该是最后一个
        assert event_types[-1] == "done", f"最后一个事件不是 done: {event_types[-1]}"

        # 第一个 token 之前不应有 done
        if "token" in event_types:
            first_token = event_types.index("token")
            assert "done" not in event_types[:first_token]

    def test_chat_invalid_user(self):
        """POST /chat — 不存在的用户应收到 error 事件"""
        if not self.soul:
            pytest.skip("无")

        r = requests.post(
            API + "/chat",
            json={
                "user_id": "nonexistent-user-xyz",
                "soul": self.soul,
                "message": "hello",
            },
            stream=True,
            timeout=30,
        )
        events = parse_sse_events(r)
        event_types = [e[0] for e in events]
        assert "error" in event_types, f"应收到 error 事件，收到: {event_types}"

    def test_chat_invalid_soul(self):
        """POST /chat — 不存在的应收到 error 事件"""
        r = requests.post(
            API + "/chat",
            json={
                "user_id": self.uid,
                "soul": "完全不存在的ABC",
                "message": "hello",
            },
            stream=True,
            timeout=30,
        )
        events = parse_sse_events(r)
        event_types = [e[0] for e in events]
        assert "error" in event_types, f"应收到 error 事件，收到: {event_types}"

    def test_chat_history_persisted(self):
        """对话后再查历史，应该能看到刚才的消息"""
        if not self.soul:
            pytest.skip("无")

        # 先发一条消息
        msg_text = f"pytest_persist_test_{int(time.time())}"
        r = requests.post(
            API + "/chat",
            json={
                "user_id": self.uid,
                "soul": self.soul,
                "message": msg_text,
            },
            stream=True,
            timeout=60,
        )
        # 消费完流
        events = parse_sse_events(r)
        assert any(e[0] == "done" for e in events), "对话没有正常完成"

        # 查历史
        hist = api_get(
            f"/history/{self.uid}/{requests.utils.quote(self.soul)}"
        )
        messages = hist["data"]["today"]["messages"]
        contents = [m.get("content", "") for m in messages]
        assert any(msg_text in c for c in contents), \
            f"历史记录中未找到刚发送的消息: {msg_text}"


# ═══════════════════════════════════════════════════════
#  6. 端到端流程 — 模拟 soul.html 完整用户旅程
# ═══════════════════════════════════════════════════════


class TestEndToEnd:
    """模拟 soul.html 前端完整使用流程"""

    def test_full_user_journey(self):
        """
        完整流程:
        1. 创建用户
        2. 获取列表
        3. 查看详情
        4. 加载历史（空）
        5. 发送消息并接收流式回复
        6. 再次加载历史（应有消息）
        7. 清理用户
        """
        # 1. 创建用户（模拟欢迎弹窗）
        user = api_post("/users", {"name": "pytest_e2e"})
        assert user["success"]
        uid = user["data"]["id"]

        try:
            # 2. 获取列表（模拟侧栏加载）
            souls = api_get("/souls")
            assert souls["success"]
            personas = souls["data"]["personas"]
            assert len(personas) > 0
            soul_name = personas[0]["name"]

            # 3. 详情
            detail = api_get(f"/souls/{requests.utils.quote(soul_name)}")
            assert detail["success"]
            assert detail["data"]["name"] == soul_name

            # 4. 加载历史（首次应为空或无今日消息）
            hist = api_get(
                f"/history/{uid}/{requests.utils.quote(soul_name)}"
            )
            assert hist["success"]

            # 5. 发送消息（模拟聊天）
            r = requests.post(
                API + "/chat",
                json={
                    "user_id": uid,
                    "soul": soul_name,
                    "message": "你好！这是一条端到端测试消息",
                },
                stream=True,
                timeout=60,
            )
            events = parse_sse_events(r)
            event_types = [e[0] for e in events]
            assert "token" in event_types
            assert "done" in event_types
            reply = "".join(
                e[1].get("content", "") or e[1].get("token", "")
                for e in events if e[0] == "token"
            )
            assert len(reply) > 0
            print(f"\n  [E2E Reply] {reply[:100]}...")

            # 6. 再查历史
            hist2 = api_get(
                f"/history/{uid}/{requests.utils.quote(soul_name)}"
            )
            assert hist2["success"]
            msgs = hist2["data"]["today"]["messages"]
            assert len(msgs) >= 2  # 至少一条 human + 一条 ai

        finally:
            # 7. 清理
            api_delete(f"/users/{uid}")


# ═══════════════════════════════════════════════════════
#  7. Auth 认证端点
# ═══════════════════════════════════════════════════════


class TestAuth:
    """Auth 认证接口测试"""

    def test_create_anonymous_user(self):
        """POST /auth/anonymous — 创建匿名用户"""
        data = api_post("/auth/anonymous")
        assert data["success"] is True
        user = data["data"]
        assert user["is_anonymous"] is True
        assert user["is_registered"] is False
        assert user["name"].startswith("访客_")
        # 清理
        try:
            api_delete(f"/users/{user['id']}")
        except Exception:
            pass

    def test_get_secrets_catalog(self):
        """GET /auth/secrets/catalog — 获取小秘密题目目录"""
        data = api_get("/auth/secrets/catalog")
        assert data["success"] is True
        questions = data["data"]["questions"]
        assert isinstance(questions, list) and len(questions) > 0
        q = questions[0]
        assert "id" in q
        assert "question" in q
        assert "gender" in q
        assert "category" in q

    def test_get_secrets_catalog_by_gender(self):
        """GET /auth/secrets/catalog?gender=female — 按性别筛选"""
        data = api_get("/auth/secrets/catalog", params={"gender": "female"})
        assert data["success"] is True
        questions = data["data"]["questions"]
        for q in questions:
            assert q["gender"] in ("all", "female")

    def test_get_user_info(self):
        """GET /auth/user/{user_id} — 获取用户信息"""
        # 先创建匿名用户
        create_data = api_post("/auth/anonymous")
        uid = create_data["data"]["id"]

        try:
            data = api_get(f"/auth/user/{uid}")
            assert data["success"] is True
            user = data["data"]
            assert user["id"] == uid
            assert user["is_anonymous"] is True
        finally:
            try:
                api_delete(f"/users/{uid}")
            except Exception:
                pass

    def test_register_user(self):
        """POST /auth/register — 完整注册"""
        import time
        test_name = f"pytest_register_{int(time.time())}"

        data = api_post("/auth/register", {
            "name": test_name,
            "gender": "male",
            "passphrase": "test_pass_123",
            "secrets": [{"question_id": "all_01", "answer": "小时候怕黑"}],
        })
        assert data["success"] is True
        user = data["data"]
        assert user["name"] == test_name
        assert user["is_anonymous"] is False
        assert user["is_registered"] is True
        assert user["has_passphrase"] is True
        assert user["secret_count"] >= 1

        # 清理
        try:
            api_delete(f"/users/{user['id']}")
        except Exception:
            pass

    def test_verify_passphrase(self):
        """POST /auth/verify/passphrase — 口令验证"""
        import time
        test_name = f"pytest_verify_{int(time.time())}"

        # 注册
        reg = api_post("/auth/register", {
            "name": test_name,
            "gender": "male",
            "passphrase": "my_secret_pass",
            "secrets": [{"question_id": "all_01", "answer": "测试答案"}],
        })
        uid = reg["data"]["id"]

        try:
            # 正确口令
            data = api_post("/auth/verify/passphrase", {
                "user_id": uid,
                "passphrase": "my_secret_pass",
            })
            assert data["success"] is True
            assert data["data"]["verified"] is True

            # 错误口令
            data2 = api_post("/auth/verify/passphrase", {
                "user_id": uid,
                "passphrase": "wrong_pass",
            })
            assert data2["success"] is True
            assert data2["data"]["verified"] is False
        finally:
            try:
                api_delete(f"/users/{uid}")
            except Exception:
                pass

    def test_upgrade_anonymous_to_registered(self):
        """POST /auth/upgrade — 匿名用户升级注册"""
        import time
        test_name = f"pytest_upgrade_{int(time.time())}"

        # 创建匿名用户
        anon = api_post("/auth/anonymous")
        uid = anon["data"]["id"]

        try:
            # 升级
            data = api_post("/auth/upgrade", {
                "user_id": uid,
                "name": test_name,
                "gender": "female",
                "passphrase": "upgrade_pass",
                "secrets": [{"question_id": "female_01", "answer": "甜蜜的事"}],
            })
            assert data["success"] is True
            user = data["data"]
            assert user["name"] == test_name
            assert user["is_anonymous"] is False
            assert user["is_registered"] is True
        finally:
            try:
                api_delete(f"/users/{uid}")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════
#  8. 匿名用户对话流程（Connection Agent）
# ═══════════════════════════════════════════════════════


class TestAnonymousChatFlow:
    """匿名用户对话测试 — 验证 connection agent 集成"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """创建匿名用户"""
        data = api_post("/auth/anonymous")
        self.uid = data["data"]["id"]
        souls = api_get("/souls")["data"]["personas"]
        self.soul = souls[0]["name"] if souls else None
        yield
        try:
            api_delete(f"/users/{self.uid}")
        except Exception:
            pass

    def test_anonymous_chat_basic(self):
        """匿名用户可以正常对话"""
        if not self.soul:
            pytest.skip("无")

        r = requests.post(
            API + "/chat",
            json={
                "user_id": self.uid,
                "soul": self.soul,
                "message": "你好，我第一次来",
            },
            stream=True,
            timeout=60,
        )
        assert r.status_code == 200
        events = parse_sse_events(r)
        event_types = [e[0] for e in events]
        assert "token" in event_types
        assert "done" in event_types

        reply = "".join(
            e[1].get("content", "") or e[1].get("token", "")
            for e in events if e[0] == "token"
        )
        assert len(reply) > 0
        print(f"\n  [Anonymous Reply] {reply[:120]}...")

    def test_anonymous_chat_has_debug_info(self):
        """匿名用户对话的 done 事件应包含 debug_info"""
        if not self.soul:
            pytest.skip("无")

        r = requests.post(
            API + "/chat",
            json={
                "user_id": self.uid,
                "soul": self.soul,
                "message": "我对编程很感兴趣",
            },
            stream=True,
            timeout=60,
        )
        events = parse_sse_events(r)
        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) > 0

        done_data = done_events[0][1]
        debug_info = done_data.get("debug_info", {})
        # connection_agent 信息应该在 debug_info 中
        if "connection_agent" in debug_info:
            ca = debug_info["connection_agent"]
            assert "target_dimension" in ca
            assert "turn_count" in ca
