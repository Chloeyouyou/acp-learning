"""作者侧 CLI：人审 _pending 里的候选题，approve 入库 / reject 删除。

自动闸门只保"对错"，教学质量（提示口吻、认知根因是否真点破）要人扫一眼。
  python -m app.tools.review_patterns --list           # 列出+预览
  python -m app.tools.review_patterns --approve BP-GEN-XXXXXX
  python -m app.tools.review_patterns --reject  BP-GEN-XXXXXX
  python -m app.tools.review_patterns                   # 交互逐个审
"""

import argparse

import yaml

from ..config import PATTERNS_DIR

PENDING = PATTERNS_DIR / "_pending"


def _load(pid):
    path = PENDING / f"{pid}.yaml"
    if not path.is_file():
        return None, None
    return path, yaml.safe_load(path.read_text(encoding="utf-8"))


def _preview(p: dict):
    print(f"\n{'='*60}\n[{p.get('id')}] {p.get('name')}  "
          f"({p.get('category')}/{p.get('difficulty')}/{p.get('symptom')}/{p.get('thinking_pattern')})")
    print(f"🧠 认知根因: {p.get('cognitive_root')}")
    print(f"⚙ 代码机制: {p.get('root_cause')}")
    print(f"--- buggy_code ---\n{p.get('buggy_code')}")
    print(f"期望输出: {p.get('expected_output')!r}")
    hl = p.get("hint_ladder", {})
    print(f"提示 L0: {hl.get('L0')}\n提示 L5: {hl.get('L5')}")
    print(f"内化问题: {p.get('internalize_questions')}")


def _pending_ids():
    if not PENDING.is_dir():
        return []
    return sorted(f.stem for f in PENDING.glob("*.yaml"))


def approve(pid) -> bool:
    path, p = _load(pid)
    if not p:
        print(f"找不到 {pid}"); return False
    dest_dir = PATTERNS_DIR / p.get("category", "_misc")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{pid}.yaml"
    path.rename(dest)
    print(f"✓ 入库：{dest}")
    return True


def reject(pid) -> bool:
    path, _ = _load(pid)
    if not path:
        print(f"找不到 {pid}"); return False
    path.unlink()
    print(f"✗ 已删除 {pid}")
    return True


def main():
    ap = argparse.ArgumentParser(description="人审 _pending 候选题")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--approve")
    ap.add_argument("--reject")
    args = ap.parse_args()

    if args.approve:
        approve(args.approve); return
    if args.reject:
        reject(args.reject); return

    ids = _pending_ids()
    if not ids:
        print("_pending 为空。先 python -m app.tools.gen_patterns 生成。"); return

    if args.list:
        for pid in ids:
            _, p = _load(pid)
            _preview(p)
        print(f"\n共 {len(ids)} 道待审。approve/reject："
              f"\n  python -m app.tools.review_patterns --approve <id>")
        return

    # 交互逐个审
    for pid in ids:
        _, p = _load(pid)
        _preview(p)
        ans = input("\n[a]入库 / [r]删除 / [s]跳过 / [q]退出 > ").strip().lower()
        if ans == "a":
            approve(pid)
        elif ans == "r":
            reject(pid)
        elif ans == "q":
            break


if __name__ == "__main__":
    main()
