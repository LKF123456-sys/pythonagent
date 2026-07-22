"""流式标签解析器单元测试：覆盖 thinking/answer 标签解析、不完整标签处理、flush 刷出。

测试策略：
- 完整标签解析：覆盖 thinking/answer 开始与结束标签
- 不完整标签处理：覆盖标签跨 token 截断的场景
- 普通文本输出：覆盖无标签的普通文本流
- flush 方法：覆盖流结束时刷出剩余缓冲区
- 边界场景：覆盖空输入、标签不匹配状态、嵌套标签
"""

import pytest  # 导入 pytest 测试框架

from app.agents.stream_parser import (  # 导入被测的流式解析器
    ParserState,  # 导入解析器状态枚举
    StreamEvent,  # 导入流事件数据类
    TagStreamParser,  # 导入标签流解析器
    _is_partial_tag_suffix,  # 导入部分标签后缀检测函数
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture  # 声明为 pytest 夹具
def parser():  # 定义解析器夹具
    """提供一个新的 TagStreamParser 实例。"""
    return TagStreamParser()  # 返回新的解析器实例


# ============================================================
# thinking 标签解析测试
# ============================================================

class TestThinkingTagParsing:
    """测试 thinking 标签的解析。"""

    def test_complete_thinking_tag_parsed(self, parser):
        """测试完整的 thinking 标签被正确解析。"""
        # 喂入完整 thinking 标签
        events = parser.feed("<thinking>hello</thinking>")  # 喂入完整标签
        # 断言产生 thinking 类型事件
        thinking_events = [e for e in events if e.type == "thinking"]  # 筛选 thinking 事件
        # 断言 thinking 事件内容为 hello
        assert any(e.content == "hello" for e in thinking_events)  # 验证内容
        # 断言最终状态为 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态

    def test_thinking_tag_split_across_tokens(self, parser):
        """测试 thinking 标签跨 token 截断。"""
        # 分段喂入 thinking 标签
        all_events = []  # 收集所有事件
        all_events.extend(parser.feed("<thin"))  # 第一段
        all_events.extend(parser.feed("king>hello</"))  # 第二段
        all_events.extend(parser.feed("thinking>"))  # 第三段
        # 断言 thinking 事件包含 hello
        thinking_content = "".join(e.content for e in all_events if e.type == "thinking")  # 拼接 thinking 内容
        assert "hello" in thinking_content  # 验证内容

    def test_thinking_content_split_across_tokens(self, parser):
        """测试 thinking 内容跨 token 截断。"""
        # 先进入 thinking 状态
        parser.feed("<thinking>")  # 进入 thinking 状态
        # 分段喂入内容
        events = []  # 收集事件
        events.extend(parser.feed("hel"))  # 第一段内容
        events.extend(parser.feed("lo"))  # 第二段内容
        events.extend(parser.feed("world"))  # 第三段内容
        # 断言所有事件类型为 thinking
        assert all(e.type == "thinking" for e in events)  # 验证事件类型
        # 断言拼接内容正确
        content = "".join(e.content for e in events)  # 拼接内容
        assert content == "helloworld"  # 验证内容

    def test_only_thinking_open_tag(self, parser):
        """测试只有 thinking 开始标签。"""
        # 喂入 thinking 开始标签
        events = parser.feed("<thinking>")  # 喂入开始标签
        # 断言状态为 IN_THINKING
        assert parser.state == ParserState.IN_THINKING  # 验证状态

    def test_thinking_close_without_open_treated_as_text(self, parser):
        """测试无对应开始标签的结束标签被当作普通文本。"""
        # 喂入无对应开始的结束标签
        events = parser.feed("</thinking>")  # 喂入结束标签
        # 断言状态仍为 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态
        # 断言产生 token 事件（当作普通文本）
        token_events = [e for e in events if e.type == "token"]  # 筛选 token 事件
        # 结束标签被当作普通文本输出
        assert any("</thinking>" in e.content for e in token_events)  # 验证当作文本


# ============================================================
# answer 标签解析测试
# ============================================================

class TestAnswerTagParsing:
    """测试 answer 标签的解析。"""

    def test_complete_answer_tag_parsed(self, parser):
        """测试完整的 answer 标签被正确解析。"""
        # 喂入完整 answer 标签
        events = parser.feed("<answer>response</answer>")  # 喂入完整标签
        # 断言产生 token 事件（answer 内容作为 token 类型）
        token_events = [e for e in events if e.type == "token"]  # 筛选 token 事件
        # 断言 token 事件包含 response
        assert any("response" in e.content for e in token_events)  # 验证内容
        # 断言最终状态为 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态

    def test_answer_tag_split_across_tokens(self, parser):
        """测试 answer 标签跨 token 截断。"""
        # 分段喂入 answer 标签
        all_events = []  # 收集所有事件
        all_events.extend(parser.feed("<ans"))  # 第一段
        all_events.extend(parser.feed("wer>hi</"))  # 第二段
        all_events.extend(parser.feed("answer>"))  # 第三段
        # 断言 token 事件包含 hi
        token_content = "".join(e.content for e in all_events if e.type == "token")  # 拼接 token 内容
        assert "hi" in token_content  # 验证内容

    def test_answer_content_split_across_tokens(self, parser):
        """测试 answer 内容跨 token 截断。"""
        # 先进入 answer 状态
        parser.feed("<answer>")  # 进入 answer 状态
        # 分段喂入内容
        events = []  # 收集事件
        events.extend(parser.feed("res"))  # 第一段内容
        events.extend(parser.feed("ponse"))  # 第二段内容
        # 断言所有事件类型为 token
        assert all(e.type == "token" for e in events)  # 验证事件类型
        # 断言拼接内容正确
        content = "".join(e.content for e in events)  # 拼接内容
        assert content == "response"  # 验证内容

    def test_only_answer_open_tag(self, parser):
        """测试只有 answer 开始标签。"""
        # 喂入 answer 开始标签
        events = parser.feed("<answer>")  # 喂入开始标签
        # 断言状态为 IN_ANSWER
        assert parser.state == ParserState.IN_ANSWER  # 验证状态


# ============================================================
# thinking + answer 组合解析测试
# ============================================================

class TestCombinedTagParsing:
    """测试 thinking 和 answer 标签组合解析。"""

    def test_thinking_then_answer(self, parser):
        """测试先 thinking 后 answer 的完整流。"""
        # 喂入完整流
        events = parser.feed("<thinking>思考</thinking><answer>回答</answer>")  # 喂入完整流
        # 提取 thinking 内容
        thinking_content = "".join(e.content for e in events if e.type == "thinking")  # 拼接 thinking 内容
        # 断言 thinking 内容包含"思考"
        assert "思考" in thinking_content  # 验证 thinking 内容
        # 提取 token 内容
        token_content = "".join(e.content for e in events if e.type == "token")  # 拼接 token 内容
        # 断言 token 内容包含"回答"
        assert "回答" in token_content  # 验证 answer 内容
        # 断言状态为 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态

    def test_text_before_tags(self, parser):
        """测试标签前的普通文本。"""
        # 喂入带前缀文本的流
        events = parser.feed("prefix<thinking>think</thinking>")  # 喂入带前缀的流
        # 提取 token 内容
        token_content = "".join(e.content for e in events if e.type == "token")  # 拼接 token 内容
        # 断言 token 内容包含 prefix
        assert "prefix" in token_content  # 验证前缀文本

    def test_text_between_tags(self, parser):
        """测试标签之间的普通文本。"""
        # 喂入标签间有文本的流
        events = parser.feed("<thinking>think</thinking>middle<answer>ans</answer>")  # 喂入带中间文本的流
        # 提取 token 内容
        token_content = "".join(e.content for e in events if e.type == "token")  # 拼接 token 内容
        # 断言 token 内容包含 middle
        assert "middle" in token_content  # 验证中间文本


# ============================================================
# 不完整标签处理测试
# ============================================================

class TestPartialTagHandling:
    """测试不完整标签的处理。"""

    def test_partial_open_tag_buffered(self, parser):
        """测试不完整的开始标签被缓冲。"""
        # 喂入不完整标签
        events = parser.feed("<thin")  # 喂入不完整标签
        # 断言没有事件产出（被缓冲）
        assert len(events) == 0  # 验证无事件
        # 继续喂入剩余部分
        events = parser.feed("king>content</thinking>")  # 喂入剩余部分
        # 断言产出 thinking 事件
        thinking_events = [e for e in events if e.type == "thinking"]  # 筛选 thinking 事件
        assert any("content" in e.content for e in thinking_events)  # 验证内容

    def test_partial_close_tag_buffered(self, parser):
        """测试不完整的结束标签被缓冲。"""
        # 先进入 thinking 状态
        parser.feed("<thinking>content")  # 进入 thinking 状态
        # 喂入不完整结束标签
        events = parser.feed("</thin")  # 喂入不完整结束标签
        # 断言没有事件产出（被缓冲）
        assert len(events) == 0  # 验证无事件
        # 继续喂入剩余部分
        events = parser.feed("king>")  # 喂入剩余部分
        # 断言状态回到 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态

    def test_is_partial_tag_suffix_function(self):
        """测试 _is_partial_tag_suffix 函数。"""
        # 断言 "<thi" 是不完整标签后缀
        assert _is_partial_tag_suffix("<thi") is True  # 验证不完整标签
        # 断言 "<answer" 是不完整标签后缀
        assert _is_partial_tag_suffix("<answer") is True  # 验证不完整标签
        # 断言 "</ans" 是不完整标签后缀
        assert _is_partial_tag_suffix("</ans") is True  # 验证不完整标签
        # 断言 "hello" 不是不完整标签后缀
        assert _is_partial_tag_suffix("hello") is False  # 验证非标签
        # 断言空字符串不是不完整标签后缀
        assert _is_partial_tag_suffix("") is False  # 验证空字符串

    def test_single_angle_bracket_not_buffered(self, parser):
        """测试单个尖括号不被缓冲。"""
        # 喂入单个尖括号
        events = parser.feed("hello < world")  # 喂入含尖括号的文本
        # 断言产出 token 事件
        token_events = [e for e in events if e.type == "token"]  # 筛选 token 事件
        # 断言事件内容包含尖括号
        content = "".join(e.content for e in token_events)  # 拼接内容
        assert "<" in content  # 验证包含尖括号


# ============================================================
# flush 方法测试
# ============================================================

class TestFlushMethod:
    """测试 flush 方法。"""

    def test_flush_empty_buffer_returns_no_events(self, parser):
        """测试 flush 空缓冲区返回空列表。"""
        # 调用 flush
        events = parser.flush()  # 调用 flush
        # 断言返回空列表
        assert events == []  # 验证返回空列表

    def test_flush_remaining_buffer(self, parser):
        """测试 flush 刷出剩余缓冲区内容。"""
        # 喂入不完整标签（会留在缓冲区等待更多输入）
        parser.feed("<thin")  # 喂入不完整标签前缀，留存在缓冲区
        # 调用 flush
        events = parser.flush()  # 调用 flush
        # 断言产出事件
        assert len(events) == 1  # 验证事件数量
        # 断言事件内容为剩余文本
        assert events[0].content == "<thin"  # 验证内容

    def test_flush_partial_tag_as_text(self, parser):
        """测试 flush 将不完整标签当作普通文本输出。"""
        # 喂入不完整标签（标签前缀）
        parser.feed("<thin")  # 喂入不完整 thinking 标签前缀
        # 调用 flush
        events = parser.flush()  # 调用 flush
        # 断言产出 token 事件
        assert len(events) >= 1  # 验证事件数量
        # 断言事件类型为 token
        assert all(e.type == "token" for e in events)  # 验证事件类型

    def test_flush_clears_buffer(self, parser):
        """测试 flush 后缓冲区被清空。"""
        # 喂入不完整标签（会留在缓冲区）
        parser.feed("<ans")  # 喂入不完整 answer 标签前缀
        # 调用 flush
        parser.flush()  # 调用 flush
        # 再次调用 flush 应返回空列表
        events = parser.flush()  # 再次调用 flush
        # 断言返回空列表
        assert events == []  # 验证返回空列表

    def test_flush_in_thinking_state(self, parser):
        """测试在 thinking 状态下 flush 产出 thinking 事件。"""
        # 进入 thinking 状态并喂入部分结束标签（留在缓冲区）
        parser.feed("<thinking>content</thin")  # content 被输出，</thin 留在缓冲区
        # 直接调用 flush 刷出剩余
        events = parser.flush()  # 调用 flush
        # 断言至少有一个事件
        assert len(events) >= 1  # 验证事件数量
        # 断言事件类型为 thinking（因仍在 thinking 状态）
        assert all(e.type == "thinking" for e in events)  # 验证事件类型


# ============================================================
# reset 方法测试
# ============================================================

class TestResetMethod:
    """测试 reset 方法。"""

    def test_reset_clears_state(self, parser):
        """测试 reset 清除状态。"""
        # 进入 thinking 状态
        parser.feed("<thinking>content")  # 进入 thinking 状态
        # 断言状态为 IN_THINKING
        assert parser.state == ParserState.IN_THINKING  # 验证状态
        # 调用 reset
        parser.reset()  # 调用 reset
        # 断言状态回到 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态
        # 断言缓冲区为空
        assert parser._buffer == ""  # 验证缓冲区

    def test_reset_clears_buffer(self, parser):
        """测试 reset 清空缓冲区。"""
        # 喂入不完整标签（前缀会留存在缓冲区）
        parser.feed("<ans")  # 喂入不完整 answer 标签前缀
        # 断言缓冲区非空
        assert parser._buffer != ""  # 验证缓冲区非空
        # 调用 reset
        parser.reset()  # 调用 reset
        # 断言缓冲区为空
        assert parser._buffer == ""  # 验证缓冲区为空

    def test_reset_allows_reuse(self, parser):
        """测试 reset 后解析器可重新使用。"""
        # 第一次使用
        parser.feed("<thinking>first</thinking>")  # 第一次使用
        # 重置
        parser.reset()  # 重置
        # 第二次使用
        events = parser.feed("<thinking>second</thinking>")  # 第二次使用
        # 断言 thinking 内容包含 second
        thinking_content = "".join(e.content for e in events if e.type == "thinking")  # 拼接内容
        assert "second" in thinking_content  # 验证内容


# ============================================================
# 边界场景测试
# ============================================================

class TestEdgeCases:
    """测试边界场景。"""

    def test_empty_string_input(self, parser):
        """测试空字符串输入。"""
        # 喂入空字符串
        events = parser.feed("")  # 喂入空字符串
        # 断言返回空列表
        assert events == []  # 验证返回空列表

    def test_no_tags_text(self, parser):
        """测试无标签的纯文本。"""
        # 喂入纯文本
        events = parser.feed("just plain text")  # 喂入纯文本
        # 断言产出 token 事件
        token_events = [e for e in events if e.type == "token"]  # 筛选 token 事件
        # 断言拼接内容为完整文本
        content = "".join(e.content for e in token_events)  # 拼接内容
        assert content == "just plain text"  # 验证内容

    def test_consecutive_feeds_without_tags(self, parser):
        """测试连续喂入无标签文本。"""
        # 连续喂入文本
        events = []  # 收集事件
        events.extend(parser.feed("hello "))  # 第一段
        events.extend(parser.feed("world"))  # 第二段
        # 断言拼接内容正确
        content = "".join(e.content for e in events)  # 拼接内容
        assert content == "hello world"  # 验证内容

    def test_nested_thinking_not_supported(self, parser):
        """测试嵌套 thinking 标签（不支持嵌套）。"""
        # 喂入嵌套标签
        events = parser.feed("<thinking>outer<thinking>inner</thinking></thinking>")  # 喂入嵌套标签
        # 断言最终状态为 NORMAL
        assert parser.state == ParserState.NORMAL  # 验证状态

    def test_stream_event_dataclass(self):
        """测试 StreamEvent 数据类。"""
        # 创建默认 StreamEvent
        event = StreamEvent(type="token")  # 创建事件
        # 断言默认 content 为空字符串
        assert event.content == ""  # 验证默认内容
        # 断言 type 字段
        assert event.type == "token"  # 验证类型

    def test_tag_at_end_of_buffer(self, parser):
        """测试标签在缓冲区末尾。"""
        # 喂入文本加标签
        events = parser.feed("text<thinking>")  # 喂入文本加开始标签
        # 断言状态为 IN_THINKING
        assert parser.state == ParserState.IN_THINKING  # 验证状态
        # 断言产出 token 事件（text 部分）
        token_events = [e for e in events if e.type == "token"]  # 筛选 token 事件
        assert any("text" in e.content for e in token_events)  # 验证内容

    def test_multiple_thinking_blocks(self, parser):
        """测试多个 thinking 块。"""
        # 喂入多个 thinking 块
        events = parser.feed("<thinking>first</thinking>middle<thinking>second</thinking>")  # 喂入多个块
        # 提取 thinking 内容
        thinking_content = "".join(e.content for e in events if e.type == "thinking")  # 拼接 thinking 内容
        # 断言包含两个 thinking 内容
        assert "first" in thinking_content  # 验证第一个内容
        assert "second" in thinking_content  # 验证第二个内容
        # 断言 token 内容包含 middle
        token_content = "".join(e.content for e in events if e.type == "token")  # 拼接 token 内容
        assert "middle" in token_content  # 验证中间文本
