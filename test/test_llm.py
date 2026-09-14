"""独立测试 LLM 配置与原始响应。

运行方式（项目根目录）：
    python test/test_llm.py

脚本不会调用知乎或写入数据库，只发送一条最小 Chat Completions 请求，
并打印配置（隐藏密钥）、HTTP/SDK 返回对象和原始 JSON，便于定位响应格式问题。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from openai import OpenAI  # noqa: E402
from agent.runtime.model_config import (  # noqa: E402
    is_placeholder,
    load_model_values,
    model_env_path,
    model_setting,
)


def main() -> int:
    env_path = model_env_path(None)
    values = load_model_values(env_path)
    api_key = model_setting("LLM_API_KEY", values) or model_setting("OPENAI_API_KEY", values)
    base_url = model_setting("LLM_BASE_URL", values) or model_setting("OPENAI_BASE_URL", values, "https://api.openai.com/v1")
    model = model_setting("LLM_MODEL", values) or model_setting("OPENAI_MODEL", values)

    print(f"[llm-test] env_file={env_path}")
    print(f"[llm-test] base_url={base_url}")
    print(f"[llm-test] model={model}")
    print(f"[llm-test] api_key={'configured' if api_key and not is_placeholder(api_key) else 'missing/placeholder'}")
    if not api_key or is_placeholder(api_key) or not model:
        print("[llm-test] ERROR: LLM_API_KEY/LLM_MODEL 未配置")
        return 2

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        print("[llm-test] sending chat.completions request...")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请只回复：LLM_TEST_OK"}],
            temperature=0,
            max_tokens=4096,
        )
        print(f"[llm-test] response_type={type(response).__name__}")
        print("[llm-test] response_dump:")
        print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2, default=str))
        print(f"[llm-test] choices_count={len(response.choices or [])}")
        if response.choices:
            message = response.choices[0].message
            print(f"[llm-test] message_content={message.content!r}")
            print(f"[llm-test] tool_calls={message.tool_calls!r}")
        return 0
    except Exception as exc:
        print(f"[llm-test] ERROR type={type(exc).__name__}: {exc!r}")
        cause = exc.__cause__
        if cause:
            print(f"[llm-test] cause type={type(cause).__name__}: {cause!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
