"""聊天完整链路集成测试：提问 → 路由 → 回答 → 持久化（含标题生成、多轮历史）。"""

import asyncio
import uuid

import pytest

from app.services import chat_service


async def _chat(client, headers, question: str, session_id: str = None):
    payload = {"question": question}
    if session_id:
        payload["session_id"] = session_id
    return await client.post("/api/chat", headers=headers, json=payload)


# ============================================================
# 非流式聊天端点
# ============================================================

class TestChatEndpoint:
    async def test_chat_returns_answer(self, client, auth_headers, fake_llm):
        resp = await _chat(client, auth_headers, "什么是量子计算？")
        assert resp.status_code == 200
        data = resp.json()
        assert "这是假的最终回答" in data["answer"]
        assert data["session_id"]
        assert data["error"] is None

    async def test_chat_requires_auth(self, client):
        resp = await client.post("/api/chat", json={"question": "你好"})
        assert resp.status_code in (401, 403)

    async def test_chat_empty_question_rejected(self, client, auth_headers):
        resp = await client.post("/api/chat", headers=auth_headers, json={"question": ""})
        assert resp.status_code == 422

    async def test_chat_search_route(self, client, auth_headers, fake_llm):
        """SEARCH 路由：搜索节点使用 FakeTavily，正常返回回答。"""
        fake_llm.route = "SEARCH"
        resp = await _chat(client, auth_headers, "今天的新闻")
        assert resp.status_code == 200
        assert "这是假的最终回答" in resp.json()["answer"]

    async def test_chat_rag_route(self, client, auth_headers, fake_llm, app):
        """RAG 路由：先注入文档到向量库，再提问。"""
        fake_llm.route = "RAG"
        app.state.vector_store.documents["手册.txt"] = [
            {"text": "系统操作手册内容", "section_title": "手册"}
        ]
        resp = await _chat(client, auth_headers, "文档里说了什么")
        assert resp.status_code == 200
        assert "这是假的最终回答" in resp.json()["answer"]


# ============================================================
# 持久化：消息 / 会话 / 标题
# ============================================================

class TestChatPersistence:
    async def test_messages_persisted(self, client, auth_headers):
        resp = await _chat(client, auth_headers, "帮我记住这个问题")
        session_id = resp.json()["session_id"]

        msg_resp = await client.get(
            f"/api/conversations/{session_id}/messages", headers=auth_headers
        )
        assert msg_resp.status_code == 200
        messages = msg_resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    async def test_conversation_created(self, client, auth_headers):
        resp = await _chat(client, auth_headers, "创建一个会话")
        session_id = resp.json()["session_id"]

        conv_resp = await client.get("/api/conversations", headers=auth_headers)
        assert conv_resp.status_code == 200
        convs = conv_resp.json()["conversations"]
        assert any(c["session_id"] == session_id for c in convs)

    async def test_title_generated_after_first_turn(self, client, auth_headers):
        """首轮结束后后台异步生成标题。"""
        resp = await _chat(client, auth_headers, "关于人工智能的问题")
        session_id = resp.json()["session_id"]

        await asyncio.sleep(0.3)  # 等待后台标题生成任务完成

        conv_resp = await client.get("/api/conversations", headers=auth_headers)
        convs = conv_resp.json()["conversations"]
        target = next(c for c in convs if c["session_id"] == session_id)
        assert target["title"] == "假的对话标题"

    async def test_multi_turn_accumulates_messages(self, client, auth_headers):
        """同一会话多轮对话，消息数累加。"""
        session_id = uuid.uuid4().hex
        await _chat(client, auth_headers, "第一轮问题", session_id)
        await _chat(client, auth_headers, "第二轮问题", session_id)

        msg_resp = await client.get(
            f"/api/conversations/{session_id}/messages", headers=auth_headers
        )
        messages = msg_resp.json()["messages"]
        assert len(messages) == 4  # 两轮 × (user + assistant)


# ============================================================
# 流式聊天生成器（chat_service.chat_stream）
# ============================================================

class TestChatStream:
    async def test_stream_emits_full_event_sequence(self, client, auth_headers, app):
        """chat_stream 应产出 status/thinking/token/done 事件序列。"""
        # 注册真实用户（FK 约束需要有效 user_id）
        reg = await client.post(
            "/api/auth/register",
            json={"username": f"stream_{uuid.uuid4().hex[:8]}", "password": "secret123"},
        )
        user_id = reg.json()["user_id"]

        events = []
        async for event in chat_service.chat_stream(
            user_id=user_id, question="流式测试问题"
        ):
            events.append(event)

        types = [e.type for e in events]
        assert "status" in types
        assert "thinking" in types
        assert "token" in types
        assert "done" in types

        # done 事件携带剥离标签后的完整回答
        done = next(e for e in events if e.type == "done")
        assert done.answer == "这是假的最终回答"

        # thinking 事件携带思考内容
        thinking_text = "".join(e.content for e in events if e.type == "thinking")
        assert "这是假的思考过程" in thinking_text

    async def test_stream_status_nodes_in_order(self, client, auth_headers, app):
        """状态事件应按工作流顺序推送节点。"""
        reg = await client.post(
            "/api/auth/register",
            json={"username": f"order_{uuid.uuid4().hex[:8]}", "password": "secret123"},
        )
        user_id = reg.json()["user_id"]

        nodes = []
        async for event in chat_service.chat_stream(
            user_id=user_id, question="节点顺序测试"
        ):
            if event.type == "status":
                nodes.append(event.node)

        # preprocess → supervisor → answer → store_memory（DIRECT 路由）
        assert nodes[0] == "preprocess"
        assert nodes[1] == "supervisor"
        assert "answer" in nodes
        assert nodes[-1] == "store_memory"

    async def test_stream_persists_assistant_message(self, client, auth_headers, app):
        """流式完成后助手消息应被持久化。"""
        reg = await client.post(
            "/api/auth/register",
            json={"username": f"persist_{uuid.uuid4().hex[:8]}", "password": "secret123"},
        )
        user_id = reg.json()["user_id"]
        session_id = uuid.uuid4().hex

        async for _ in chat_service.chat_stream(
            user_id=user_id, question="持久化测试", session_id=session_id
        ):
            pass

        from app.repositories import message_repo

        messages = await message_repo.get_messages(session_id)
        assert len(messages) == 2
        assert messages[-1]["role"] == "assistant"
