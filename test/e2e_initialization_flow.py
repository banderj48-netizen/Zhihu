"""端到端初始化流程测试：所有选择自动选 A。

运行：
    python test/e2e_initialization_flow.py
    python test/e2e_initialization_flow.py --user-id local-demo-user
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def call(base: str, method: str, path: str, body: Any, user_id: str) -> Any:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json", "X-User-Id": user_id}
    print(f"\n{'=' * 20} {method} {path} {'=' * 20}")
    print("REQUEST:", json.dumps(body, ensure_ascii=False, indent=2))
    req = urllib.request.Request(base.rstrip("/") + path, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read().decode("utf-8", errors="replace")
            print(f"HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} ERROR")
        print("RESPONSE:", raw)
        raise
    except Exception as exc:
        print(f"REQUEST ERROR {type(exc).__name__}: {exc!r}")
        raise
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = raw
    print("RESPONSE:", json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", default="local-demo-user")
    args = parser.parse_args()
    uid = args.user_id
    try:
        created = call(args.base_url, "POST", "/v1/twin/initializations", {}, uid)
        session_id = str(created.get("id") or created.get("session_id"))
        if not session_id or session_id == "None":
            raise RuntimeError(f"响应中没有 session_id/id: {created}")
        print(f"\nSESSION_ID={session_id}")

        # 性格题为可选步骤；读取题目并统一选择中间值 3。
        try:
            personality = call(args.base_url, "GET", "/v1/personality/questions", None, uid)
            items = personality.get("items", personality) if isinstance(personality, dict) else personality
            answers = {str(item.get("id")): 3 for item in (items or []) if isinstance(item, dict) and item.get("id")}
            call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/personality", {"data": {"answers": answers}}, uid)
        except Exception as exc:
            print(f"[flow] personality step skipped: {type(exc).__name__}: {exc!r}")

        domains = {"interests": [{"domain_id": "computer.02.02", "level": 3}], "expertise": []}
        call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/domains", {"data": domains}, uid)

        opinion = call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/opinion-questions", {"count": 5, "domain_ids": ["computer.02.02"]}, uid)
        opinion_answers = [{"question_id": q.get("question_id"), "selected_option_id": "opt_a", "custom_text": ""} for q in opinion.get("questions", [])]
        call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/opinion-answers", {"data": {"answers": opinion_answers}}, uid)

        social = call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/social-questions", {"count": 5}, uid)
        social_answers = [{"question_id": q.get("question_id"), "selected_option_id": "opt_a", "elapsed_seconds": 1} for q in social.get("questions", [])]
        call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/social-answers", {"data": {"answers": social_answers}}, uid)

        call(args.base_url, "POST", f"/v1/twin/initializations/{session_id}/complete", {"identity": {"name": "自动化测试用户"}}, uid)
        call(args.base_url, "GET", f"/v1/twin/initializations/{session_id}", None, uid)
        print("\n[flow] ALL STEPS COMPLETED")
        return 0
    except Exception:
        print("\n[flow] FAILED; 请查看上方最后一个 REQUEST/RESPONSE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
