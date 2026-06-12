"""导师LLM路径端到端测试：真实调用DeepSeek，走两轮对话观察引导行为与事件产出。"""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
with client:
    r = client.post("/api/sessions", json={"student_id": "stu_live", "pattern_id": "BP-BOUNDARY-001"})
    sid = r.json()["session_id"]
    print("=== 带雷代码 ===")
    print(r.json()["code"])

    print("=== 第1轮：学生描述现象 ===")
    r = client.post(f"/api/sessions/{sid}/messages",
                    json={"content": "我运行这段代码报错了：IndexError: list index out of range，不知道怎么回事"})
    assert r.status_code == 200, r.text
    d = r.json()
    print("导师:", d["reply"])
    print("阶段:", d["stage"], "| 提示级别:", d["hint_level"], "| 事件:", d["events_emitted"])

    print()
    print("=== 第2轮：学生直接要答案 ===")
    r = client.post(f"/api/sessions/{sid}/messages",
                    json={"content": "你别绕弯子了，直接告诉我正确代码怎么写"})
    assert r.status_code == 200, r.text
    d = r.json()
    print("导师:", d["reply"])
    print("阶段:", d["stage"], "| 提示级别:", d["hint_level"], "| 事件:", d["events_emitted"])

    print()
    print("=== 第3轮：学生说出定位和归因 ===")
    r = client.post(f"/api/sessions/{sid}/messages",
                    json={"content": "我明白了，问题在第4行的 range(len(arr) + 1)，因为长度为3的列表下标只有0到2，"
                                     "但range多走了一步，最后一次访问了arr[3]，越界了"})
    assert r.status_code == 200, r.text
    d = r.json()
    print("导师:", d["reply"])
    print("阶段:", d["stage"], "| 提示级别:", d["hint_level"], "| 事件:", d["events_emitted"])

    print()
    print("=== 画像 ===")
    r = client.get("/api/students/stu_live/profile")
    print(r.json())
