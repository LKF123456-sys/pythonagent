"""智能体模块单元测试：标签流解析器 / 路由决策 / 工具 / 语义切片 / 缓存。

这些测试不依赖 FastAPI 应用与数据库，属于纯单元测试。
"""

import pytest
from langchain_core.messages import AIMessage

from app.agents.stream_parser import ParserState, StreamEvent, TagStreamParser
from app.agents.nodes import route_after_supervisor, _execute_tool_calls, search_node
from app.agents.graph import _chunk_text, _extract_action, _extract_token_usage, run_agent_stream
from app.agents.llm import supervisor_decide_cached
from app.agents.tools import AGENT_TOOLS, calculator, get_current_time
from app.core.constants import RouteAction
from app.memory.rag import format_memories_context, semantic_chunk


# ============================================================
# TagStreamParser：标签流解析器
# ============================================================

def _collect(tokens):
    """将 token 序列喂入解析器，返回 (thinking 文本, answer 文本)。"""
    parser = TagStreamParser()
    thinking, answer = [], []
    for tok in tokens:
        for ev in parser.feed(tok):
            (thinking if ev.type == "thinking" else answer).append(ev.content)
    for ev in parser.flush():
        (thinking if ev.type == "thinking" else answer).append(ev.content)
    return "".join(thinking), "".join(answer)


class TestTagStreamParser:
    def test_thinking_then_answer(self):
        """完整标签序列应正确分离思考与回答。"""
        thinking, answer = _collect(
            ["<thinking>", "我在思考", "</thinking>", "<answer>", "最终回答", "</answer>"]
        )
        assert thinking == "我在思考"
        assert answer == "最终回答"

    def test_tag_split_across_tokens(self):
        """标签跨 token 截断时应正确缓冲并识别。"""
        # "<thinking>" 被拆成 "<thi" 和 "nking>"
        thinking, answer = _collect(["<thi", "nking>", "思考内容", "</think", "ing>", "<answer>", "答", "</answer>"])
        assert thinking == "思考内容"
        assert answer == "答"

    def test_char_by_char_streaming(self):
        """逐字符流式输入也应正确解析。"""
        full = "<thinking>逐步思考</thinking><answer>逐字回答</answer>"
        thinking, answer = _collect(list(full))
        assert thinking == "逐步思考"
        assert answer == "逐字回答"

    def test_plain_text_without_tags(self):
        """无标签的普通文本应全部作为 token 输出。"""
        thinking, answer = _collect(["你好", "，", "世界"])
        assert thinking == ""
        assert answer == "你好，世界"

    def test_text_before_tag(self):
        """标签前的残留文本应作为当前状态的内容输出。"""
        parser = TagStreamParser()
        events = parser.feed("前缀文本<thinking>思考</thinking>")
        types = [(e.type, e.content) for e in events]
        # 前缀文本在 NORMAL 状态下输出为 token
        assert ("token", "前缀文本") in types
        assert ("thinking", "思考") in types

    def test_mismatched_close_tag_treated_as_text(self):
        """状态不匹配的结束标签应当作普通文本处理。"""
        parser = TagStreamParser()
        # NORMAL 状态下出现 </thinking>，不应切换状态
        events = parser.feed("</thinking>普通文本")
        parser.flush()
        combined = "".join(e.content for e in events)
        assert "普通文本" in combined
        assert parser.state == ParserState.NORMAL

    def test_flush_emits_pending_buffer(self):
        """流结束时 flush 应刷出因疑似标签前缀而暂存的内容。"""
        parser = TagStreamParser()
        parser.feed("<answer>回答<")  # 结尾 "<" 使 "回答<" 整体暂存缓冲区
        events = parser.flush()
        assert any("回答" in e.content for e in events)

    def test_reset_clears_state(self):
        """reset 应重置状态与缓冲区。"""
        parser = TagStreamParser()
        parser.feed("<thinking>思考中")
        parser.reset()
        assert parser.state == ParserState.NORMAL
        assert parser.flush() == []

    def test_partial_tag_held_in_buffer(self):
        """可能是标签前缀的内容应暂存缓冲区，不提前输出。"""
        parser = TagStreamParser()
        events = parser.feed("结尾是<")  # "<" 可能是标签开头
        # "<" 应被缓冲，不立即输出
        assert all("<" not in e.content for e in events)


# ============================================================
# 路由决策
# ============================================================

class TestRouting:
    async def test_search_node_degrades_when_tavily_fails(self, monkeypatch):
        """联网搜索异常时不应中断整条智能体链路，而应返回可解释降级结果。"""
        class FakeKeywordLLM:
            async def ainvoke(self, messages):
                return AIMessage(content="LangGraph 最新进展")

        class BrokenTavilyClient:
            def __init__(self, api_key):
                self.api_key = api_key

            def search(self, *args, **kwargs):
                raise RuntimeError("tavily timeout")

        monkeypatch.setattr("app.agents.nodes.create_llm", lambda temperature=0.0: FakeKeywordLLM())
        monkeypatch.setattr("tavily.TavilyClient", BrokenTavilyClient)
        result = await search_node({"user_question": "LangGraph 最新进展"})
        assert "search_results" in result
        assert "联网搜索暂时不可用" in result["search_results"]
        assert "tavily timeout" in result["search_results"]

    def test_route_search(self):
        assert route_after_supervisor({"action": RouteAction.SEARCH}) == "search"

    def test_route_rag(self):
        assert route_after_supervisor({"action": RouteAction.RAG}) == "rag"

    def test_route_direct(self):
        assert route_after_supervisor({"action": RouteAction.DIRECT}) == "answer"

    def test_route_default_is_answer(self):
        """缺少 action 时默认路由到 answer。"""
        assert route_after_supervisor({}) == "answer"


# ============================================================
# 图辅助提取函数
# ============================================================

class TestGraphHelpers:
    async def test_run_agent_stream_falls_back_to_final_ai_message_when_no_stream_token(self, monkeypatch):
        """测试模型流事件缺失时，完成事件仍应回退使用最终 AIMessage 内容。"""
        class FakeGraph:
            async def astream_events(self, initial_state, config, version):
                yield {"event": "on_chain_start", "name": "answer", "data": {}}
                yield {
                    "event": "on_chain_end",
                    "name": "answer",
                    "data": {"output": {"messages": [AIMessage(content="最终回答")]}},
                }

        monkeypatch.setattr("app.agents.graph.get_graph", lambda: FakeGraph())

        events = [
            event async for event in run_agent_stream(
                user_question="你好",
                thread_id="test-thread",
                user_id=1,
            )
        ]
        done = events[-1]
        assert done.type == "done"
        assert done.answer == "最终回答"

    async def test_run_agent_stream_falls_back_from_nested_answer_output(self, monkeypatch):
        """测试回答节点输出嵌套在 output 字段时，完成事件仍能提取最终回答。"""
        class FakeGraph:
            async def astream_events(self, initial_state, config, version):
                yield {"event": "on_chain_start", "name": "search", "data": {}}
                yield {"event": "on_chain_start", "name": "answer", "data": {}}
                yield {
                    "event": "on_chain_end",
                    "name": "answer",
                    "data": {"output": {"output": {"messages": [AIMessage(content="搜索后的最终回答")]}}},
                }

        monkeypatch.setattr("app.agents.graph.get_graph", lambda: FakeGraph())

        events = [
            event async for event in run_agent_stream(
                user_question="帮我搜索 LangGraph 最新进展",
                thread_id="test-thread",
                user_id=1,
            )
        ]
        done = events[-1]
        assert done.type == "done"
        assert done.answer == "搜索后的最终回答"

    async def test_run_agent_stream_reads_final_answer_from_checkpoint_state(self, monkeypatch):
        """测试事件流未捕获答案时，应从 LangGraph 最终检查点状态读取真实 AIMessage。"""
        class FakeSnapshot:
            values = {"messages": [AIMessage(content="2026年世界杯决赛将于7月19日举行。")]}

        class FakeGraph:
            async def astream_events(self, initial_state, config, version):
                yield {"event": "on_chain_start", "name": "preprocess", "data": {}}
                yield {"event": "on_chain_start", "name": "supervisor", "data": {}}
                yield {"event": "on_chain_start", "name": "search", "data": {}}
                yield {"event": "on_chain_start", "name": "answer", "data": {}}
                yield {"event": "on_chain_start", "name": "store_memory", "data": {}}

            async def aget_state(self, config):
                return FakeSnapshot()

        monkeypatch.setattr("app.agents.graph.get_graph", lambda: FakeGraph())

        events = [
            event async for event in run_agent_stream(
                user_question="世界杯今年的什么时候结束",
                thread_id="test-thread",
                user_id=1,
            )
        ]
        done = events[-1]
        assert done.type == "done"
        assert done.answer == "2026年世界杯决赛将于7月19日举行。"

    async def test_run_agent_stream_parses_answer_tag_from_checkpoint_state(self, monkeypatch):
        """测试从最终检查点恢复的带标签内容，应只把answer正文作为最终回答。"""
        class FakeSnapshot:
            values = {"messages": [AIMessage(content="<thinking>内部推理</thinking><answer>今天阜阳多云，气温约25到32度。</answer>")]}

        class FakeGraph:
            async def astream_events(self, initial_state, config, version):
                yield {"event": "on_chain_start", "name": "search", "data": {}}
                yield {"event": "on_chain_start", "name": "answer", "data": {}}
                yield {"event": "on_chain_start", "name": "store_memory", "data": {}}

            async def aget_state(self, config):
                return FakeSnapshot()

        monkeypatch.setattr("app.agents.graph.get_graph", lambda: FakeGraph())

        events = [
            event async for event in run_agent_stream(
                user_question="阜阳今天的天气",
                thread_id="test-thread",
                user_id=1,
            )
        ]
        done = events[-1]
        assert done.type == "done"
        assert done.answer == "今天阜阳多云，气温约25到32度。"

    async def test_run_agent_stream_reads_dict_ai_message_from_checkpoint_state(self, monkeypatch):
        """测试最终检查点 messages 为字典格式时，也能提取 AI 回答。"""
        class FakeSnapshot:
            values = {"messages": [{"type": "ai", "content": "<answer>阜阳今天多云。</answer>"}]}

        class FakeGraph:
            async def astream_events(self, initial_state, config, version):
                yield {"event": "on_chain_start", "name": "search", "data": {}}
                yield {"event": "on_chain_start", "name": "answer", "data": {}}
                yield {"event": "on_chain_start", "name": "store_memory", "data": {}}

            async def aget_state(self, config):
                return FakeSnapshot()

        monkeypatch.setattr("app.agents.graph.get_graph", lambda: FakeGraph())

        events = [
            event async for event in run_agent_stream(
                user_question="阜阳今天的天气",
                thread_id="test-thread",
                user_id=1,
            )
        ]
        done = events[-1]
        assert done.type == "done"
        assert done.answer == "阜阳今天多云。"

    def test_chunk_text_string(self):
        class C:
            content = "你好"
        assert _chunk_text(C()) == "你好"

    def test_chunk_text_list(self):
        class C:
            content = [{"text": "A"}, {"text": "B"}, "C"]
        assert _chunk_text(C()) == "ABC"

    def test_chunk_text_empty(self):
        class C:
            content = ""
        assert _chunk_text(C()) == ""

    def test_extract_action_from_dict(self):
        assert _extract_action({"action": "SEARCH"}) == "SEARCH"

    def test_extract_action_missing(self):
        assert _extract_action({"other": 1}) == ""
        assert _extract_action("not-a-dict") == ""

    def test_extract_token_usage_metadata(self):
        class Out:
            usage_metadata = {"total_tokens": 42}
            response_metadata = None
        assert _extract_token_usage(Out()) == 42

    def test_extract_token_usage_response_meta(self):
        class Out:
            usage_metadata = None
            response_metadata = {"token_usage": {"total_tokens": 7}}
        assert _extract_token_usage(Out()) == 7

    def test_extract_token_usage_none(self):
        assert _extract_token_usage(None) == 0


# ============================================================
# 路由缓存
# ============================================================

class TestRouteCache:
    async def test_cache_hit_avoids_recompute(self):
        """相同输入第二次调用应命中缓存，不再执行 decide_fn。"""
        calls = []

        async def decide(question, history):
            calls.append(question)
            return RouteAction.DIRECT

        r1 = await supervisor_decide_cached("缓存测试问题", "", decide)
        r2 = await supervisor_decide_cached("缓存测试问题", "", decide)
        assert r1 == r2 == RouteAction.DIRECT
        assert len(calls) == 1  # 仅第一次真正调用

    async def test_different_question_not_cached(self):
        """不同问题不应命中同一缓存。"""
        calls = []

        async def decide(question, history):
            calls.append(question)
            return RouteAction.SEARCH

        await supervisor_decide_cached("问题甲", "", decide)
        await supervisor_decide_cached("问题乙", "", decide)
        assert len(calls) == 2


# ============================================================
# Function Calling 工具
# ============================================================

class TestTools:
    def test_calculator_basic(self):
        result = calculator.invoke({"expression": "2**10 + 3"})
        assert "1027" in result

    def test_calculator_rejects_unsafe(self):
        """非白名单字符应被拒绝。"""
        result = calculator.invoke({"expression": "__import__('os')"})
        assert "不支持" in result

    def test_get_current_time(self):
        result = get_current_time.invoke({})
        assert "当前时间" in result

    def test_agent_tools_registered(self):
        names = {t.name for t in AGENT_TOOLS}
        assert "calculator" in names
        assert "get_current_time" in names

    def test_execute_tool_calls(self):
        """_execute_tool_calls 应执行工具并拼接结果。"""
        calls = [{"name": "calculator", "args": {"expression": "1+1"}}]
        result = _execute_tool_calls(calls)
        assert "calculator" in result
        assert "2" in result


# ============================================================
# 语义切片
# ============================================================

class TestSemanticChunk:
    def test_chunk_by_markdown_headers(self):
        content = "# 第一章\n这是第一章的内容。\n\n## 第二节\n这是第二节的内容。"
        chunks = semantic_chunk(content, chunk_size=500, chunk_overlap=50)
        assert len(chunks) >= 2
        titles = {c["section_title"] for c in chunks}
        assert "第一章" in titles
        assert "第二节" in titles

    def test_chunk_link_fields(self):
        chunks = semantic_chunk("# A\n段落一\n\n# B\n段落二\n\n# C\n段落三")
        assert chunks[0]["prev_chunk_id"] is None
        assert chunks[-1]["next_chunk_id"] is None
        if len(chunks) >= 2:
            assert chunks[0]["next_chunk_id"] == 1
            assert chunks[1]["prev_chunk_id"] == 0

    def test_long_paragraph_sliding_window(self):
        long_text = "字" * 1200
        chunks = semantic_chunk(long_text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) >= 2
        assert all(len(c["text"]) <= 500 for c in chunks)

    def test_empty_content(self):
        assert semantic_chunk("") == []

    def test_format_memories_context(self):
        memories = [
            {"content": "历史对话内容", "metadata": {"timestamp": "2024-01-01"}},
        ]
        ctx = format_memories_context(memories)
        assert "长期记忆" in ctx
        assert "历史对话内容" in ctx

    def test_format_memories_empty(self):
        assert format_memories_context([]) == ""
