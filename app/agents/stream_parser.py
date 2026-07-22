"""健壮的标签流解析器：状态机实现，替代脆弱的 endswith 判断链。

将 LLM 流式输出中的 <thinking>...</thinking> 和 <answer>...</answer> 标签
实时解析为结构化事件，支持标签跨 token 截断的场景。
"""

from dataclasses import dataclass, field  # 从dataclasses导入dataclass装饰器和field字段定义函数
from enum import Enum, auto  # 从enum模块导入Enum枚举基类和auto自动值生成函数
from typing import List  # 从typing导入List类型，用于列表类型注解


class ParserState(Enum):  # 定义解析器状态枚举类，继承自Enum
    """解析器状态。"""

    NORMAL = auto()        # 普通文本（无标签包裹）  # 普通文本状态，自动生成值
    IN_THINKING = auto()   # 在 <thinking> 标签内  # 处于thinking标签内的状态
    IN_ANSWER = auto()     # 在 <answer> 标签内  # 处于answer标签内的状态


@dataclass  # 应用dataclass装饰器，自动生成__init__等方法
class StreamEvent:  # 定义流事件数据类
    """解析产出的流事件。"""

    type: str              # "thinking" | "token"  # 事件类型字段：thinking或token
    content: str = ""  # 事件内容字段，默认为空字符串


# 需要识别的标签及其对应的目标状态与事件类型
_OPEN_TAGS = {  # 定义开始标签映射字典
    "<thinking>": (ParserState.IN_THINKING, "thinking"),  # thinking开始标签映射到IN_THINKING状态和thinking事件
    "<answer>": (ParserState.IN_ANSWER, "token"),  # answer开始标签映射到IN_ANSWER状态和token事件
}
_CLOSE_TAGS = {  # 定义结束标签映射字典
    "</thinking>": ParserState.NORMAL,  # thinking结束标签映射回NORMAL状态
    "</answer>": ParserState.NORMAL,  # answer结束标签映射回NORMAL状态
}

# 所有标签（用于前缀缓冲检测）
_ALL_TAGS = list(_OPEN_TAGS.keys()) + list(_CLOSE_TAGS.keys())  # 合并开始标签和结束标签为完整标签列表


def _is_partial_tag_suffix(buffer: str) -> bool:  # 定义检测部分标签后缀的私有函数，返回布尔值
    """
    检测缓冲区末尾是否是某个标签的不完整前缀。

    例如 buffer 以 "<thi" 结尾，可能是 "<thinking>" 的开头，
    此时应继续缓冲等待更多字符，而不是立即输出。
    """
    for tag in _ALL_TAGS:  # 遍历所有标签
        # 检查 buffer 末尾是否匹配 tag 的某个真前缀
        for prefix_len in range(1, len(tag)):  # 遍历从1到标签长度-1的前缀长度
            if buffer.endswith(tag[:prefix_len]):  # 如果缓冲区以该前缀结尾
                return True  # 返回True，表示可能是未完成标签
    return False  # 不匹配任何标签前缀则返回False


@dataclass  # 应用dataclass装饰器，自动生成__init__等方法
class TagStreamParser:  # 定义标签流解析器类
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

    state: ParserState = field(default=ParserState.NORMAL)  # 解析器当前状态字段，默认为NORMAL
    _buffer: str = field(default="")  # 内部缓冲区字段，默认为空字符串

    def feed(self, token: str) -> List[StreamEvent]:  # 定义喂入token的方法，返回事件列表
        """
        输入一个 token，返回解析出的事件列表。

        通过缓冲区机制处理标签跨 token 截断的情况。
        """
        self._buffer += token  # 将新token追加到缓冲区
        events: List[StreamEvent] = []  # 创建事件列表

        while self._buffer:  # 当缓冲区非空时循环
            # 优先检测完整标签
            consumed = self._try_match_tags(events)  # 尝试匹配标签
            if consumed:  # 如果消费了内容（匹配到标签或输出前缀）
                continue  # 继续循环处理剩余缓冲区

            # 缓冲区末尾可能是未完成标签，暂不输出
            if _is_partial_tag_suffix(self._buffer):  # 如果缓冲区末尾是未完成标签
                break  # 跳出循环，等待更多token

            # 安全输出全部缓冲区内容
            events.append(self._make_event(self._buffer))  # 将缓冲区内容生成为事件
            self._buffer = ""  # 清空缓冲区

        return events  # 返回解析出的事件列表

    def _try_match_tags(self, events: List[StreamEvent]) -> bool:  # 定义尝试匹配标签的私有方法，返回是否消费
        """尝试在缓冲区头部匹配完整标签，匹配成功则消费并返回 True。"""
        # 匹配开始标签
        for tag, (new_state, _) in _OPEN_TAGS.items():  # 遍历开始标签字典
            if self._buffer.startswith(tag):  # 如果缓冲区以该标签开头
                # 输出标签前的残留内容
                self._buffer = self._buffer[len(tag):]  # 从缓冲区中移除该标签
                self.state = new_state  # 切换到对应的新状态
                return True  # 返回True表示已消费

        # 匹配结束标签（仅在对应状态内有效）
        for tag, new_state in _CLOSE_TAGS.items():  # 遍历结束标签字典
            if self._buffer.startswith(tag):  # 如果缓冲区以该标签开头
                if (tag == "</thinking>" and self.state == ParserState.IN_THINKING) or \
                   (tag == "</answer>" and self.state == ParserState.IN_ANSWER):
                    self._buffer = self._buffer[len(tag):]  # 从缓冲区中移除该标签
                    self.state = new_state  # 切换到NORMAL状态
                    return True  # 返回True表示已消费
                # 状态不匹配的结束标签当作普通文本消费一个字符
                break  # 跳出循环，让外层处理

        # 在缓冲区内查找标签位置（标签可能不在头部）
        earliest_idx, earliest_tag = self._find_earliest_tag()  # 查找缓冲区中最先出现的标签
        if earliest_idx > 0:  # 如果标签不在头部（索引大于0）
            # 输出标签前的文本
            prefix = self._buffer[:earliest_idx]  # 提取标签前的文本前缀
            self._buffer = self._buffer[earliest_idx:]  # 更新缓冲区为从标签开始的部分
            events.append(self._make_event(prefix))  # 将前缀文本生成为事件
            return True  # 返回True表示已消费

        return False  # 未匹配到任何标签，返回False

    def _find_earliest_tag(self) -> tuple:  # 定义查找最早标签的私有方法，返回(索引, 标签)元组
        """查找缓冲区中最先出现的完整标签，返回 (索引, 标签) 或 (-1, None)。"""
        earliest_idx = -1  # 最早索引初始为-1（未找到）
        earliest_tag = None  # 最早标签初始为None
        for tag in _ALL_TAGS:  # 遍历所有标签
            idx = self._buffer.find(tag)  # 在缓冲区中查找标签位置
            if idx != -1 and (earliest_idx == -1 or idx < earliest_idx):  # 如果找到且比当前最早更早
                earliest_idx = idx  # 更新最早索引
                earliest_tag = tag  # 更新最早标签
        return earliest_idx, earliest_tag  # 返回最早索引和标签

    def _make_event(self, content: str) -> StreamEvent:  # 定义生成事件的私有方法，返回StreamEvent
        """根据当前状态生成对应类型的事件。"""
        if self.state == ParserState.IN_THINKING:  # 如果当前在thinking状态
            return StreamEvent(type="thinking", content=content)  # 生成thinking类型事件
        return StreamEvent(type="token", content=content)  # 否则生成token类型事件

    def flush(self) -> List[StreamEvent]:  # 定义刷出剩余内容的方法，返回事件列表
        """流结束时刷出剩余缓冲区。"""
        events: List[StreamEvent] = []  # 创建事件列表
        if self._buffer:  # 如果缓冲区非空
            events.append(self._make_event(self._buffer))  # 将剩余缓冲区内容生成为事件
            self._buffer = ""  # 清空缓冲区
        return events  # 返回事件列表

    def reset(self) -> None:  # 定义重置解析器状态的方法
        """重置解析器状态。"""
        self.state = ParserState.NORMAL  # 重置状态为NORMAL
        self._buffer = ""  # 清空缓冲区