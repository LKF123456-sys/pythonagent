"""WebSocket 端点测试：连接认证 / 消息流 / 中断生成 / 多用户并发。

使用 starlette TestClient（同步）：其上下文管理器自行触发应用 lifespan，
避免与 httpx AsyncClient 混用导致的跨事件循环 asyncpg 连接问题。
"""

import contextlib
import uuid

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient


# ============================================================
# 辅助函数
# ============================================================

def _register_token(tc: TestClient) -> str:
    """通过 HTTP 注册真实用户并返回 access token（WS 认证需要 DB 中存在的用户）。"""
    resp = tc.post(
        "/api/auth/register",
        json={"username": f"ws_{uuid.uuid4().hex[:10]}", "password": "secret123"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _recv_until(ws, predicate, max_msgs: int = 500) -> list:
    """持续接收消息直到谓词命中，返回全部收到的消息（含命中那条）。"""
    received = []
    for _ in range(max_msgs):
        msg = ws.receive_json()
        received.append(msg)
        if predicate(msg):
            return received
    raise AssertionError(f"在 {max_msgs} 条消息内未满足条件，最后几条: {received[-5:]}")


def _drain_chat_flow(ws) -> list:
    """发送聊天后收集完整事件流直到 done。"""
    return _recv_until(ws, lambda m: m.get("type") == "done")


# ============================================================
# 连接与认证
# ============================================================

class TestWSConnection:
    def test_connect_with_valid_token_and_ping(self, ws_app):
        """有效 token 握手成功，ping → pong。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with tc.websocket_connect(f"/ws/chat/s1?token={token}") as ws:
                ws.send_json({"type": "ping"})
                msg = ws.receive_json()
                assert msg["type"] == "pong"

    def test_connect_with_invalid_token_rejected(self, ws_app):
        """无效 token：握手阶段直接关闭，close code = 4401。"""
        with TestClient(ws_app) as tc:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with tc.websocket_connect("/ws/chat/s1?token=invalid-token-here"):
                    pass  # pragma: no cover
            assert exc_info.value.code == 4401

    def test_connect_with_missing_token_rejected(self, ws_app):
        """缺失 token：同样在握手阶段被拒绝。"""
        with TestClient(ws_app) as tc:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with tc.websocket_connect("/ws/chat/s1"):
                    pass  # pragma: no cover
            assert exc_info.value.code == 4401

    def test_connect_with_refresh_token_rejected(self, ws_app):
        """refresh token 不能用于 WS 认证（type != access）。"""
        with TestClient(ws_app) as tc:
            resp = tc.post(
                "/api/auth/register",
                json={"username": f"rf_{uuid.uuid4().hex[:10]}", "password": "secret123"},
            )
            refresh_token = resp.json()["refresh_token"]
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with tc.websocket_connect(f"/ws/chat/s1?token={refresh_token}"):
                    pass  # pragma: no cover
            assert exc_info.value.code == 4401


# ============================================================
# 消息流
# ============================================================

class TestWSMessageFlow:
    def test_chat_emits_full_event_sequence(self, ws_app):
        """发送 chat → 依次收到 status/thinking/token/done，done 携带剥离标签后的回答。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            sid = uuid.uuid4().hex
            with tc.websocket_connect(f"/ws/chat/{sid}?token={token}") as ws:
                ws.send_json({"type": "chat", "question": "什么是量子计算？"})
                events = _drain_chat_flow(ws)

            types = [e["type"] for e in events]
            assert "status" in types
            assert "thinking" in types
            assert "token" in types
            assert types[-1] == "done"

            done = events[-1]
            assert done["answer"] == "这是假的最终回答"
            assert done["session_id"] == sid
            assert done["route"] == "DIRECT"

            thinking_text = "".join(e["content"] for e in events if e["type"] == "thinking")
            assert "这是假的思考过程" in thinking_text

    def test_chat_status_nodes_in_order(self, ws_app):
        """status 事件按工作流顺序推送节点（DIRECT 路由）。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with tc.websocket_connect(f"/ws/chat/{uuid.uuid4().hex}?token={token}") as ws:
                ws.send_json({"type": "chat", "question": "节点顺序测试"})
                events = _drain_chat_flow(ws)

            nodes = [e["node"] for e in events if e["type"] == "status"]
            assert nodes[0] == "preprocess"
            assert nodes[1] == "supervisor"
            assert "answer" in nodes
            assert nodes[-1] == "store_memory"

    def test_empty_question_returns_error(self, ws_app):
        """空问题：返回 error「问题不能为空」，连接保持可用。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with tc.websocket_connect(f"/ws/chat/{uuid.uuid4().hex}?token={token}") as ws:
                ws.send_json({"type": "chat", "question": "   "})
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert "问题不能为空" in msg["message"]

                # 连接未断开，仍可 ping
                ws.send_json({"type": "ping"})
                assert ws.receive_json()["type"] == "pong"

    def test_invalid_json_returns_error(self, ws_app):
        """非法 JSON：返回 error「消息格式无效」，连接保持可用。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with tc.websocket_connect(f"/ws/chat/{uuid.uuid4().hex}?token={token}") as ws:
                ws.send_text("这不是合法的 JSON {{{")
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert "消息格式无效" in msg["message"]

                ws.send_json({"type": "ping"})
                assert ws.receive_json()["type"] == "pong"

    def test_multi_turn_on_same_connection(self, ws_app):
        """同一连接连续两轮对话，各自收到完整 done。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            sid = uuid.uuid4().hex
            with tc.websocket_connect(f"/ws/chat/{sid}?token={token}") as ws:
                for question in ("第一轮问题", "第二轮问题"):
                    ws.send_json({"type": "chat", "question": question})
                    events = _drain_chat_flow(ws)
                    assert events[-1]["type"] == "done"
                    assert events[-1]["answer"] == "这是假的最终回答"


# ============================================================
# 中断生成
# ============================================================

class TestWSAbort:
    def test_abort_stops_generation(self, ws_app, fake_llm):
        """流式输出中发送 abort：收到 aborted done，连接保持可用。"""
        fake_llm.stream_delay = 0.02  # 放慢流式速度，确保 abort 能追上
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            sid = uuid.uuid4().hex
            with tc.websocket_connect(f"/ws/chat/{sid}?token={token}") as ws:
                ws.send_json({"type": "chat", "question": "写一篇长文"})

                # 等到流真正开始（收到首个 token）再中断
                _recv_until(ws, lambda m: m.get("type") == "token")
                ws.send_json({"type": "abort"})

                events = _recv_until(
                    ws, lambda m: m.get("type") == "done" and m.get("aborted") is True
                )
                aborted = events[-1]
                assert aborted["aborted"] is True
                assert aborted["session_id"] == sid

                # 中断后连接仍然可用
                ws.send_json({"type": "ping"})
                assert ws.receive_json()["type"] == "pong"

    def test_abort_without_active_stream_is_noop(self, ws_app):
        """无进行中的流时发送 abort：不产生 done，连接正常。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with tc.websocket_connect(f"/ws/chat/{uuid.uuid4().hex}?token={token}") as ws:
                ws.send_json({"type": "abort"})
                # 无活跃任务时服务端不发送任何消息，ping 验证连接仍正常
                ws.send_json({"type": "ping"})
                assert ws.receive_json()["type"] == "pong"


# ============================================================
# 多用户并发
# ============================================================

class TestWSConcurrency:
    def test_ten_concurrent_connections(self, ws_app):
        """10 个并发连接同时 ping/pong，互不干扰。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with contextlib.ExitStack() as stack:
                sockets = [
                    stack.enter_context(
                        tc.websocket_connect(f"/ws/chat/conc_{i}?token={token}")
                    )
                    for i in range(10)
                ]
                for ws in sockets:
                    ws.send_json({"type": "ping"})
                for ws in sockets:
                    assert ws.receive_json()["type"] == "pong"

    def test_concurrent_chat_streams_isolated(self, ws_app):
        """两个连接各自独立收到完整的 done 事件流。"""
        with TestClient(ws_app) as tc:
            token = _register_token(tc)
            with contextlib.ExitStack() as stack:
                ws_a = stack.enter_context(
                    tc.websocket_connect(f"/ws/chat/{uuid.uuid4().hex}?token={token}")
                )
                ws_b = stack.enter_context(
                    tc.websocket_connect(f"/ws/chat/{uuid.uuid4().hex}?token={token}")
                )
                ws_a.send_json({"type": "chat", "question": "连接A的问题"})
                ws_b.send_json({"type": "chat", "question": "连接B的问题"})

                done_a = _drain_chat_flow(ws_a)[-1]
                done_b = _drain_chat_flow(ws_b)[-1]
                assert done_a["answer"] == "这是假的最终回答"
                assert done_b["answer"] == "这是假的最终回答"
