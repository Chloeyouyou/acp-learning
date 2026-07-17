"""认知先验层测试（独立于 run_tests.py，主线四轮落地后再并入）。

零外部依赖：假 LLM callable + 临时目录，直接 `python test_priors.py`。
锁三条硬门槛：3证据门槛、临时态隔离、反例退休；外加注入措辞、失败关闭、拆卸纪律。
"""

import json
import re
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app.priors import (
    Evidence, PriorStore, distill_evidence, render_injection,
    PROMOTE_MIN_SOURCES, RETIRE_CONTRADICTIONS,
)
from app.priors.store import empty_data

_tests = []
def test(fn): _tests.append(fn); return fn


def _llm_returning(*payloads):
    """依次返回给定 JSON 的假 LLM；调用超出次数则重复最后一个。"""
    calls = {"n": 0}
    def fake(prompt: str) -> str:
        i = min(calls["n"], len(payloads) - 1)
        calls["n"] += 1
        return json.dumps(payloads[i], ensure_ascii=False)
    return fake


def _ev(source_id: str, text="他这局先猜着改了三次代码，才回头读报错信息"):
    return Evidence(text=text, source_id=source_id, at="2026-07-16T00:00:00+00:00")


def _new_decision(statement="遇到报错时他通常先改代码再读报错信息", temporality="durable"):
    return {"decisions": [{"action": "new", "statement": statement, "temporality": temporality}]}


# ---------------- store ----------------

@test
def store_roundtrip_and_missing():
    with tempfile.TemporaryDirectory() as d:
        store = PriorStore(d)
        data = store.load("stu_a")
        assert data == empty_data("stu_a"), "不存在应给空骨架"
        data["candidates"].append({"id": "c_1", "statement": "x", "evidence": [],
                                   "contradictions": [], "status": "candidate"})
        store.save("stu_a", data)
        again = store.load("stu_a")
        assert again["candidates"][0]["id"] == "c_1", "存取应往返一致"
        assert not list(Path(d).glob("*.tmp")), "原子写不应留临时文件"


@test
def store_rejects_unsafe_student_id():
    with tempfile.TemporaryDirectory() as d:
        store = PriorStore(d)
        for bad in ("../evil", "a/b", "", "x" * 65):
            try:
                store.load(bad)
                assert False, f"应拒绝不安全 id: {bad!r}"
            except ValueError:
                pass


@test
def transient_ttl_cleanup_on_load():
    with tempfile.TemporaryDirectory() as d:
        store = PriorStore(d)
        data = empty_data("stu_a")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        data["transient"] = [{"statement": "过期的", "expires_at": past},
                             {"statement": "还在的", "expires_at": future}]
        store.save("stu_a", data)
        loaded = store.load("stu_a")
        assert [t["statement"] for t in loaded["transient"]] == ["还在的"], "过期临时态应在读取时清掉"


# ---------------- 3 证据门槛 ----------------

@test
def promotion_needs_three_distinct_sources():
    data = empty_data("stu_a")
    llm = _llm_returning(_new_decision())
    data = distill_evidence(data, _ev("s1"), llm)
    cid = data["candidates"][0]["id"]
    support = _llm_returning({"decisions": [{"action": "support", "id": cid}]})
    data = distill_evidence(data, _ev("s2"), support)
    assert not data["priors"] and len(data["candidates"]) == 1, "2 条证据不得晋升"
    assert render_injection(data) == "", "候选不得注入"
    data = distill_evidence(data, _ev("s3"), support)
    assert not data["candidates"] and data["priors"][0]["status"] == "active", \
        f"{PROMOTE_MIN_SOURCES} 条独立证据应晋升 active"


@test
def duplicate_source_does_not_count():
    data = empty_data("stu_a")
    data = distill_evidence(data, _ev("s1"), _llm_returning(_new_decision()))
    cid = data["candidates"][0]["id"]
    support = _llm_returning({"decisions": [{"action": "support", "id": cid}]})
    for _ in range(5):
        data = distill_evidence(data, _ev("s1"), support)  # 同一来源反复喂
    assert not data["priors"], "同一来源刷 5 次也不许晋升——门槛是 3 次独立场景"
    assert len(data["candidates"][0]["evidence"]) == 1, "同源证据不重复入账"


@test
def same_statement_merges_instead_of_duplicating():
    data = empty_data("stu_a")
    llm = _llm_returning(_new_decision())
    for s in ("s1", "s2", "s3"):
        data = distill_evidence(data, _ev(s), llm)  # LLM 每次都说 new，但原句相同
    assert len(data["priors"]) == 1 and not data["candidates"], \
        "撞原句的 new 应并作 support，3 次独立来源后晋升且不开重复档"


# ---------------- 临时态隔离 ----------------

@test
def transient_never_promotes():
    data = empty_data("stu_a")
    llm = _llm_returning(_new_decision("他今天很累，不想听复杂解释", "transient"))
    for s in ("s1", "s2", "s3", "s4"):
        data = distill_evidence(data, _ev(s), llm)
    assert not data["candidates"] and not data["priors"], "临时态永不参与固化"
    assert len(data["transient"]) == 1, "同句临时态只刷新 TTL 不堆积"
    assert render_injection(data) == "", "临时态不得注入"


# ---------------- 反例退休 ----------------

@test
def two_contradictions_retire_prior():
    data = empty_data("stu_a")
    data = distill_evidence(data, _ev("s1"), _llm_returning(_new_decision()))
    cid = data["candidates"][0]["id"]
    support = _llm_returning({"decisions": [{"action": "support", "id": cid}]})
    data = distill_evidence(data, _ev("s2"), support)
    data = distill_evidence(data, _ev("s3"), support)
    contra = _llm_returning({"decisions": [{"action": "contradict", "id": cid}]})
    data = distill_evidence(data, _ev("s4"), contra)
    assert data["priors"][0]["status"] == "active", "1 次矛盾不退休"
    data = distill_evidence(data, _ev("s4"), contra)
    assert data["priors"][0]["status"] == "active", "同源矛盾不重复计数"
    data = distill_evidence(data, _ev("s5"), contra)
    assert data["priors"][0]["status"] == "retired", f"{RETIRE_CONTRADICTIONS} 次独立矛盾应退休"
    assert render_injection(data) == "", "退休先验不得注入"


# ---------------- 注入措辞 ----------------

@test
def injection_wording_and_cap():
    data = empty_data("stu_a")
    for i in range(4):
        data["priors"].append({
            "id": f"p_{i}", "statement": f"倾向{i}", "kind": "inferred", "domain": "learning",
            "evidence": [{"source_id": f"s{i}{j}", "at": ""} for j in range(3 + i)],
            "contradictions": [], "status": "active", "updated_at": f"2026-07-1{i}",
        })
    text = render_injection(data)
    assert text.count("\n- ") == 3, "最多注入 3 条"
    assert "倾向3" in text and "倾向0" not in text, "证据多者优先"
    for must in ("仅供选择讲解起点", "以本轮为准", "不是学生的标签", "不得据此跳过"):
        assert must in text, f"注入必须带硬规则措辞: {must}"
    assert "推断自 6 次经历" in text, "推断类要亮出证据次数"
    data["priors"][3]["kind"] = "stated"
    assert "他自己明确说过" in render_injection(data), "明说类要标来源"


# ---------------- 失败关闭 ----------------

@test
def garbage_llm_output_is_noop():
    data = empty_data("stu_a")
    data = distill_evidence(data, _ev("s1"), _llm_returning(_new_decision()))
    before = json.dumps(data, sort_keys=True, ensure_ascii=False)
    def boom(prompt): raise RuntimeError("LLM 挂了")
    for bad_llm in (lambda p: "这不是JSON", lambda p: '{"decisions": "不是列表"}',
                    lambda p: '{"decisions": [{"action": "new", "statement": ""}, "垃圾"]}',
                    boom):
        data = distill_evidence(data, _ev("s9"), bad_llm)
        assert json.dumps(data, sort_keys=True, ensure_ascii=False) == before, \
            "垃圾输出/异常必须无操作，不崩不脏"


@test
def overlong_statement_rejected():
    data = empty_data("stu_a")
    data = distill_evidence(data, _ev("s1"), _llm_returning(_new_decision("长" * 200)))
    assert not data["candidates"], "超长陈述是复述细节不是提炼倾向，拒收"


# ---------------- 拆卸纪律 ----------------

@test
def priors_package_has_no_host_imports():
    pkg = Path(__file__).parent / "app" / "priors"
    bad = re.compile(r"^\s*(from\s+(\.\.|app)|import\s+app)", re.M)
    for f in pkg.glob("*.py"):
        m = bad.search(f.read_text(encoding="utf-8"))
        assert not m, f"拆卸纪律破功：{f.name} 依赖宿主内部 → {m.group(0).strip()!r}"


def main():
    passed = failed = 0
    for fn in _tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
