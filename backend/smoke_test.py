"""非LLM路径冒烟测试：埋雷 → 提交修复（沙箱真跑判定）→ 事件 → 画像 → 下钻。

失败提交的导师反馈走LLM，这里打桩保持非LLM性质。判题已改为真跑代码，
所以提交的是完整程序（非代码片段），与真实用法一致。
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import tutor

FAKE_TURN = tutor.TutorTurn(
    reply="（桩）我看到你的提交没通过，我们回到刚才的分析。",
    stage_transition=None, hint_level_used="L0",
    student_progressed=False, answer_begging=False, events=[])

BUGGY = """def total(arr):
    s = 0
    for i in range(len(arr) + 1):
        s += arr[i]
    return s

print(total([1, 2, 3]))
"""
FIXED = BUGGY.replace("range(len(arr) + 1)", "range(len(arr))")

client = TestClient(app)
with client:
    r = client.get("/api/patterns")
    assert r.status_code == 200, r.text
    print("patterns:", [p["id"] for p in r.json()])

    r = client.post("/api/sessions", json={"student_id": "stu_test", "pattern_id": "BP-BOUNDARY-001"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    print("session:", sid, "| code contains mine:", "len(arr) + 1" in r.json()["code"])

    with patch.object(tutor, "_call_llm", lambda s, h: FAKE_TURN):
        r = client.post(f"/api/sessions/{sid}/submit", json={"code": BUGGY})
    assert r.json()["passed"] is False
    print("wrong fix rejected: OK")

    r = client.post(f"/api/sessions/{sid}/submit", json={"code": FIXED})
    assert r.json()["passed"] is True, r.text
    print("correct fix accepted: OK")

    # 运行端点：跑带雷代码应看到真实报错
    r = client.post(f"/api/sessions/{sid}/run", json={"code": BUGGY})
    assert "IndexError" in r.json()["stderr"], r.json()
    print("run endpoint shows real error: OK")

    r = client.get("/api/students/stu_test/profile")
    prof = r.json()
    print("profile vector:", prof["vector"])
    print("knowledge states:", prof["knowledge_states"])

    r = client.get("/api/students/stu_test/capabilities/Independent_Debug/events")
    evs = r.json()
    assert len(evs) == 1 and evs[0]["evidence"]["summary"], evs
    print("drill-down event:", evs[0]["evidence"]["summary"])

print("SMOKE TEST PASSED")
