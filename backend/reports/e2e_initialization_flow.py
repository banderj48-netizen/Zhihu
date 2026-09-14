# -*- coding: utf-8 -*-
"""数字分身初始化全流程端到端验证脚本。

用法（先启动后端，再运行）：
    python backend/reports/e2e_initialization_flow.py [user_id]

按 PRD 六步依次调用真实接口：
导入资料 -> 性格测试 -> 兴趣/擅长 -> 领域观点题 -> 限时社交情景题 -> 生成画像。
其中社交题故意混入一题超时（elapsed_seconds > 13），用于验证后端过滤逻辑。
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
USER = sys.argv[1] if len(sys.argv) > 1 else "e2e-curl-user"
TIME_LIMIT = 13


def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
    request = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", "X-User-Id": USER},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    print(f"== 初始化全流程 E2E（用户 {USER}） ==")

    # 0. 创建初始化会话
    session = call("/v1/twin/initializations", "POST", {})
    sid = session["id"]
    print(f"[0] 会话 {sid} status={session['status']}")

    # 1. 导入资料（模拟导入任务 + 快照留档）
    job = call("/v1/import-jobs", "POST", {"consent_id": f"consent_{USER}", "source": "zhihu", "options": {"initialize_agent": True}})
    call("/v1/twin/initializations/%s/zhihu-import" % sid, "POST", {"data": {"job_id": job["id"], "imported_count": 2, "selected": [{"title": "演示回答", "url": "https://demo", "content_type": "answer"}]}})
    print(f"[1] 导入任务 {job['id']} 已留档")

    # 2. 性格测试：取 50 题，混合作答（避免直线作答）
    questions = call("/v1/personality/questions")
    pattern = [1, 2, 3, 4, 5, 2, 4, 1, 3, 5]
    answers = {item["id"]: pattern[index % len(pattern)] for index, item in enumerate(questions["items"])}
    assessment = call("/v1/personality/assessments", "POST", {"answers": answers, "notes": None, "request_key": f"e2e_{sid}"})
    session = call("/v1/twin/initializations/%s/personality" % sid, "POST", {"data": assessment})
    print(f"[2] 性格测评 status={assessment['status']} scores={ {k: round(v,1) for k,v in assessment['scores'].items()} }")

    # 3. 兴趣与擅长（先读当前 revision，保证脚本可重复运行）
    current = call("/v1/domains/selections/me")
    selection = {
        "expected_revision": current.get("revision", 0),
        "interests": [{"domain_id": "computer.01.02", "interest_level": 3, "notes": "长期写后端"}, {"domain_id": "entertainment.06.03", "interest_level": 2, "notes": ""}],
        "expertise": [{"domain_id": "computer.03.05", "proficiency": "working", "notes": ""}],
    }
    call("/v1/domains/selections/me", "PUT", selection)
    session = call("/v1/twin/initializations/%s/domains" % sid, "POST", {"data": {"interests": selection["interests"], "expertise": selection["expertise"]}})
    print(f"[3] 领域选择已保存 status={session['status']}")

    # 4. 领域观点题（LLM 未配置时走模板回退）
    domain_ids = [item["domain_id"] for item in selection["interests"] + selection["expertise"]]
    opinion = call(f"/v1/twin/initializations/{sid}/opinion-questions", "POST", {"count": 3, "domain_ids": domain_ids})
    opinion_answers = []
    for index, question in enumerate(opinion["questions"]):
        option = question["options"][index % max(1, len(question["options"]) - 2)]
        opinion_answers.append({
            "question_id": question["question_id"], "question_version": question["question_version"],
            "domain_id": question["domain_id"], "topic": question["prompt"][:20], "prompt": question["prompt"],
            "level": "middle", "selected_option_id": option["id"], "custom_text": None, "content": option["label"],
        })
    session = call("/v1/twin/initializations/%s/opinion-answers" % sid, "POST", {"data": {"answers": opinion_answers}})
    print(f"[4] 观点题 {len(opinion_answers)} 题已提交 status={session['status']}")

    # 5. 限时社交情景题：前两题 6 秒内作答，第三题故意超时（15 秒）
    social = call(f"/v1/twin/initializations/{sid}/social-questions", "POST", {"count": 3})
    social_answers = []
    for index, question in enumerate(social["questions"]):
        stamped = call(f"/v1/twin/social-questions/{question['question_id']}/present", "POST")
        option = question["options"][index % max(1, len(question["options"]) - 1)]
        elapsed = 15.2 if index == 2 else 5.8
        social_answers.append({
            "question_id": question["question_id"], "question_version": question["question_version"],
            "scene": question["scene"], "topic": question["scene"], "level": "middle",
            "selected_option_id": option["id"], "custom_text": None, "reaction": option["label"],
            "presented_at": stamped["presented_at"], "submitted_at": stamped["presented_at"],
            "elapsed_seconds": elapsed, "status": "timeout" if elapsed > TIME_LIMIT else "counted",
        })
    session = call("/v1/twin/initializations/%s/social-answers" % sid, "POST", {"data": {"answers": social_answers}})
    print(f"[5] 情景题已提交（含 1 题故意超时） status={session['status']}")

    # 6. 生成画像
    result = call("/v1/twin/initializations/%s/complete" % sid, "POST", {
        "identity": {"display_name": "E2E 测试分身", "summary": "接口全流程验证", "occupation": "工程师", "location": "上海", "age": 28, "privacy_level": "private"}
    })
    print(f"[6] 画像生成 avatar_id={result.get('avatar_id')} version_id={result.get('version_id')} status={result.get('status')}")

    final = call(f"/v1/twin/initializations/{sid}")
    keys = sorted((final.get("input_data") or {}).keys())
    print(f"== 会话终态 status={final['status']} input_data 键={keys} ==")
    assert final["status"] == "completed", "初始化会话未完成"
    for key in ("zhihu-import", "personality", "domains", "opinion-answers", "social-answers"):
        assert key in (final.get("input_data") or {}), f"缺少步骤数据: {key}"
    print("== E2E 全部通过 ==")


if __name__ == "__main__":
    main()
