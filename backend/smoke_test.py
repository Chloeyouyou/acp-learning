"""非LLM路径冒烟测试：埋雷 → 提交修复（规则判定）→ 事件 → 画像 → 下钻。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
with client:
    r = client.get("/api/patterns")
    assert r.status_code == 200, r.text
    print("patterns:", [p["id"] for p in r.json()])

    r = client.post("/api/sessions", json={"student_id": "stu_test", "pattern_id": "BP-BOUNDARY-001"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    print("session:", sid, "| code contains mine:", "len(arr) + 1" in r.json()["code"])

    r = client.post(f"/api/sessions/{sid}/submit", json={"code": "for i in range(len(arr) + 1):"})
    assert r.json()["passed"] is False
    print("wrong fix rejected: OK")

    r = client.post(f"/api/sessions/{sid}/submit", json={"code": "for i in range(len(arr)):"})
    assert r.json()["passed"] is True, r.text
    print("correct fix accepted: OK")

    r = client.get("/api/students/stu_test/profile")
    prof = r.json()
    print("profile vector:", prof["vector"])
    print("knowledge states:", prof["knowledge_states"])

    r = client.get("/api/students/stu_test/capabilities/Independent_Debug/events")
    evs = r.json()
    assert len(evs) == 1 and evs[0]["evidence"]["summary"], evs
    print("drill-down event:", evs[0]["evidence"]["summary"])

print("SMOKE TEST PASSED")
