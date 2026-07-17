"""认知先验层（Cognitive Prior Layer）——可拆卸的共享核心。

从多次经历里蒸馏「这个人通常怎样理解、求助、行动」的思维默认值，
作为智能体选择讲解/回应起点的参考。经历层回答「过去发生过什么」，
本层回答「根据连续证据，他通常怎样思考——但当下如果不同，以当下为准」。
设计全文见 docs/计划/2026-07-16-认知先验层计划.md。

拆卸纪律（破一条就算失败）：
1. 本包只依赖标准库，绝不 import 宿主（app.*）内部模块；
2. LLM 以 callable 注入，存储目录由宿主传入；
3. 数据是人类可读的 JSON，手动删错误先验即生效；
4. 搬去别的项目 = 复制本目录 + 写一个薄适配器。
"""

from .distill import (
    PROMOTE_MIN_SOURCES,
    RETIRE_CONTRADICTIONS,
    TRANSIENT_TTL_HOURS,
    distill_evidence,
)
from .inject import MAX_INJECT, render_injection
from .store import Evidence, PriorStore, utcnow_iso

__all__ = [
    "Evidence", "PriorStore", "utcnow_iso",
    "distill_evidence", "render_injection",
    "PROMOTE_MIN_SOURCES", "RETIRE_CONTRADICTIONS", "TRANSIENT_TTL_HOURS", "MAX_INJECT",
]
