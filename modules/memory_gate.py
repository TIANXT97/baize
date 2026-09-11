"""Relevance Gate - decides if a message needs memory retrieval."""
import re
import time
from typing import Optional

CORRECTION_PATTERNS = re.compile(
    r'不对|不是这|你记错|错了|记错了|你说错|no,|wrong|actually|not really',
    re.IGNORECASE
)

# E3: 显式搜索意图旁路 —— 在 MEMORY_TRIGGERS 之前匹配，命中即强制通过。
# 修复前无触发词的裸关键词查询（如"启动方式"）被门控拦成空结果。
EXPLICIT_SEARCH_PATTERNS = [
    r"^(帮我查|查一下|查查|找一下|搜一下|搜索|查|看看|翻一下|找找).*",
    r".*(搜一下|查一下|回忆一下|找一下|查查|搜搜|翻一下).*",
    r".*记忆.*",
    r".*(之前|以前|上次).*(说过|提到|说过|配置|设置)",
]

MEMORY_TRIGGERS = [
    r"你还?记得", r"我之前", r"我上次", r"我以前", r"我曾经",
    r"我之前说", r"上次说", r"以前说", r"提到过", r"说过",
    r"我的偏好", r"我的习惯", r"我喜欢", r"我不喜欢",
    r"帮我回忆", r"帮我找", r"帮我查.*记忆",
    r"之前.*说过", r"记得.*吗", r"有没有.*记忆",
]

NO_MEMORY_PATTERNS = [
    r"^(天气|几点|现在|今天几号|星期)", r"^(帮我写|帮我生成|帮我创建)",
    r"^(运行|执行|跑一下)",
    r"^(好的?|收到|ok|嗯|知道了|明白|了解|没问题|可以|行)$",
]

# E3b: 门控口令白名单 —— 用户使用特定口令时自动放行（skip_gate语义），
# 即使对应的 NO_MEMORY_PATTERNS 也不拦截。配合 EXPLICIT_SEARCH_PATTERNS 处理各种口气变体。
GATE_PASS_PHRASES = [
    r"^搜一下", r"^查一下", r"^回忆一下", r"^找一下",
    r"^查查", r"^搜搜", r"^找找",
    r"^帮我查", r"^帮我找", r"^帮我回忆",
    r"^看看", r"^翻一下",
]

QUESTION_PATTERNS = re.compile(
    r'[？?]|'                                           # contains question mark
    r'(什么|怎么|为什么|如何|怎样|多少|几|谁|哪(?:里|儿)|'
    r'何时|什么时候|为何|可否|是否|能不能|会不会|要不要|'
    r'该不该|有没有|是不是|还是)|'                     # question word
    r'(吗|呢|吧)[？?]?\s*$',                            # ends with particle
    re.IGNORECASE
)


class MemoryGate:
    """Lightweight relevance gate using keyword matching + time window."""

    def __init__(self, inherit_window_sec: float = 15.0):
        self.inherit_window = inherit_window_sec
        self._last_memory_time: float = 0
        self._last_needs_memory: bool = False
        self._explicit_search_re = re.compile("|".join(EXPLICIT_SEARCH_PATTERNS), re.IGNORECASE)
        self._pass_phrase_re = re.compile("|".join(GATE_PASS_PHRASES), re.IGNORECASE)
        self._trigger_re = re.compile("|".join(MEMORY_TRIGGERS), re.IGNORECASE)
        self._no_memory_re = re.compile("|".join(NO_MEMORY_PATTERNS), re.IGNORECASE)

    def needs_memory(self, message: str, force: Optional[bool] = None) -> bool:
        # 纠正信号强制通过
        if CORRECTION_PATTERNS.search(message.strip()):
            self._update_state(True)
            return True

        if force is not None:
            self._update_state(force)
            return force
        msg = message.strip()
        if not msg:
            self._update_state(False)
            return False
        # E3: 显式搜索意图旁路（先于触发词/排除词）——裸关键词查询不被门控误杀
        if self._explicit_search_re.search(msg):
            self._update_state(True)
            return True
        # E3b: 门控口令白名单——用户说"搜一下/查一下/回忆一下"等口令时自动放行
        if self._pass_phrase_re.search(msg):
            self._update_state(True)
            return True
        if len(msg) < 15 and self._last_needs_memory:
            elapsed = time.time() - self._last_memory_time
            if elapsed < self.inherit_window:
                return True
        if self._trigger_re.search(msg):
            self._update_state(True)
            return True
        if self._no_memory_re.match(msg):
            self._update_state(False)
            return False
        # 问句常需上下文 → 触发记忆检索（除非已被 no-memory pattern 排除）
        if QUESTION_PATTERNS.search(msg):
            self._update_state(True)
            return True
        self._update_state(False)
        return False

    def _update_state(self, needs: bool):
        self._last_needs_memory = needs
        if needs:
            self._last_memory_time = time.time()
