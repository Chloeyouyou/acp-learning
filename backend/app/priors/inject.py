"""注入渲染：把 active 先验变成给智能体 system prompt 的文本块。

措辞由本包强制生成、宿主不可改写——「当前 > 先验」的覆盖序和「不贴标签」
是这一层的存在前提：先验只帮系统选更合适的起点，不替用户决定终点。
"""

MAX_INJECT = 3   # 只带最扎实的几条，先验不是越多越好

_HEADER = "\n\n[关于这个学生的长期倾向·仅供选择讲解起点]\n"

_RULES = """
使用硬规则：
1. 这些只是从过往经历推断的倾向，不是学生的标签——绝不当面复述这些观察，绝不给学生贴标签（不说「你就是XX型」）。
2. 本轮学生的实际表现或明确要求与这些倾向矛盾时，一律以本轮为准，视相应倾向不存在。
3. 只用于选择更合适的讲解起点（先给整体骨架还是先给具体小例子、台阶切多细），不得据此跳过任何引导阶段或降低内化要求。"""


def _distinct_sources(item: dict) -> int:
    return len({e.get("source_id") for e in item.get("evidence", [])})


def render_injection(data: dict) -> str:
    """无可注入先验时返回空串——宿主行为与没有这一层时完全一致。"""
    active = [p for p in data.get("priors", []) if p.get("status") == "active"]
    if not active:
        return ""
    # 证据多者优先（证据条数与新旧就是置信度），同证据数新者优先
    active.sort(key=lambda p: (_distinct_sources(p), p.get("updated_at", "")), reverse=True)
    lines = []
    for p in active[:MAX_INJECT]:
        tag = ("他自己明确说过" if p.get("kind") == "stated"
               else f"推断自 {_distinct_sources(p)} 次经历")
        lines.append(f"- {p['statement']}（{tag}）")
    return _HEADER + "\n".join(lines) + _RULES
