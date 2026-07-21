"""健壮的标签流解析器：状态机实现，替代脆弱的 endswith 判断链。

将 LLM 流式输出中的 <thinking>...</thinking> 和 <answer>...</answer> 标签
实时解析为结构化事件，支持标签跨 token 截断的场景。
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List


class ParserState(Enum):
    """解析器状态。"""

    NORMAL = auto()        # 普通文本（无标签包裹）
    IN_THINKING = auto()   # 在 <thinking> 标签内
    IN_ANSWER = auto()     # 在 <answer> 标签内


@dataclass
class StreamEvent:
    """解析产出的流事件。"""

    type: str              # "thinking" | "token"
    content: str = ""


# 需要识别的标签及其对应的目标状态与事件类型
_OPEN_TAGS = {
    "<thinking>": (ParserState.IN_THINKING, "thinking"),
    "<answer>": (ParserState.IN_ANSWER, "token"),
}
_CLOSE_TAGS = {
    "</thinking>": ParserState.NORMAL,
    "</answer>": ParserState.NORMAL,
}

# 所有标签（用于前缀缓冲检测）
_ALL_TAGS = list(_OPEN_TAGS.keys()) + list(_CLOSE_TAGS.keys())


def _is_partial_tag_suffix(buffer: str) -> bool:
    """
    检测缓冲区末尾是否是某个标签的不完整前缀。

    例如 buffer 以 "<thi" 结尾，可能是 "<thinking>" 的开头，
    此时应继续缓冲等待更多字符，而不是立即输出。
    """
    for tag in _ALL_TAGS:
        # 检查 buffer 末尾是否匹配 tag 的某个真前缀
        for prefix_len in range(1, len(tag)):
            if buffer.endswith(tag[:prefix_len]):
                return True
    return False


@dataclass
class TagStreamParser:
    """
    标签流解析器（状态机）。

    用法：
        parser = TagStreamParser()
        for token in llm_stream:
            for event in parser.feed(token):
                handle(event)
        for event in parser.flush():
            handle(event)
    """

    state: ParserState = field(default=ParserState.NORMAL)
    _buffer: str = field(default="")

    def feed(self, token: str) -> List[StreamEvent]:
        """
        输入一个 token，返回解析出的事件列表。

        通过缓冲区机制处理标签跨 token 截断的情况。
        """
        self._buffer += token
        events: List[StreamEvent] = []

        while self._buffer:
            # 优先检测完整标签
            consumed = self._try_match_tags(events)
            if consumed:
                continue

            # 缓冲区末尾可能是未完成标签，暂不输出
            if _is_partial_tag_suffix(self._buffer):
                break

            # 安全输出全部缓冲区内容
            events.append(self._make_event(self._buffer))
            self._buffer = ""

        return events

    def _try_match_tags(self, events: List[StreamEvent]) -> bool:
        """尝试在缓冲区头部匹配完整标签，匹配成功则消费并返回 True。"""
        # 匹配开始标签
        for tag, (new_state, _) in _OPEN_TAGS.items():
            if self._buffer.startswith(tag):
                # 输出标签前的残留内容
                self._buffer = self._buffer[len(tag):]
                self.state = new_state
                return True

        # 匹配结束标签（仅在对应状态内有效）
        for tag, new_state in _CLOSE_TAGS.items():
            if self._buffer.startswith(tag):
                if (tag == "</thinking>" and self.state == ParserState.IN_THINKING) or \
                   (tag == "</answer>" and self.state == ParserState.IN_ANSWER):
                    self._buffer = self._buffer[len(tag):]
                    self.state = new_state
                    return True
                # 状态不匹配的结束标签当作普通文本消费一个字符
                break

        # 在缓冲区内查找标签位置（标签可能不在头部）
        earliest_idx, earliest_tag = self._find_earliest_tag()
        if earliest_idx > 0:
            # 输出标签前的文本
            prefix = self._buffer[:earliest_idx]
            self._buffer = self._buffer[earliest_idx:]
            events.append(self._make_event(prefix))
            return True

        return False

    def _find_earliest_tag(self) -> tuple:
        """查找缓冲区中最先出现的完整标签，返回 (索引, 标签) 或 (-1, None)。"""
        earliest_idx = -1
        earliest_tag = None
        for tag in _ALL_TAGS:
            idx = self._buffer.find(tag)
            if idx != -1 and (earliest_idx == -1 or idx < earliest_idx):
                earliest_idx = idx
                earliest_tag = tag
        return earliest_idx, earliest_tag

    def _make_event(self, content: str) -> StreamEvent:
        """根据当前状态生成对应类型的事件。"""
        if self.state == ParserState.IN_THINKING:
            return StreamEvent(type="thinking", content=content)
        return StreamEvent(type="token", content=content)

    def flush(self) -> List[StreamEvent]:
        """流结束时刷出剩余缓冲区。"""
        events: List[StreamEvent] = []
        if self._buffer:
            events.append(self._make_event(self._buffer))
            self._buffer = ""
        return events

    def reset(self) -> None:
        """重置解析器状态。"""
        self.state = ParserState.NORMAL
        self._buffer = ""
