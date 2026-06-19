"""出题目标层（Planner）——决定"出什么题"，不随机。

阶段1：按显式参数产出可执行 GenTask。
阶段2（接口已留，未实现）：plan_from_weakness() 接 profile.knowledge_mastery 做画像驱动补弱 +
generation_policy.yaml 静态分布兜底 + collect_stats 填缺口（见 docs/design/07 A-5 自进化闭环）。
"""

from dataclasses import asdict, dataclass, field


@dataclass
class GenTask:
    """一个可执行的出题任务（含硬约束，喂给 generator）。"""
    category: str
    difficulty: str
    thinking_pattern: str
    error_target: str                       # RE | WA | HANG
    knowledge_points: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=lambda: {
        "must_trigger_exception": True, "must_include_edge_case": True})
    seed: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def plan_tasks(*, category, difficulty, thinking_pattern, error_target,
               knowledge_points=None, n=1, seed=None) -> list[GenTask]:
    """阶段1：显式参数 → n 个 GenTask。"""
    return [
        GenTask(
            category=category, difficulty=difficulty, thinking_pattern=thinking_pattern,
            error_target=error_target, knowledge_points=knowledge_points or [], seed=seed,
        )
        for _ in range(n)
    ]


def plan_from_weakness(db, student_id, n=1) -> list[GenTask]:  # 阶段2：留接口，未实现
    """B→E 边界：按数字孪生薄弱点生成约束。等内测有真实薄弱数据再接
    profile.knowledge_mastery / get_weakest_pattern_id + generation_policy.yaml。"""
    raise NotImplementedError("阶段2：画像驱动补弱（接口已留，待内测数据）")
