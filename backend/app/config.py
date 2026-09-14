"""应用配置。

启动时自动加载配置，无需每次手动设置环境变量。

应用配置优先级：真实环境变量 > TWINLOOP_ENV_FILE 指定文件 > 本文件内置默认值。
LLM、评判模型和 Embedding 不在此处加载，统一由独立的 .env.models 按需读取。
部署时用环境变量覆盖，本地开发直接用内置默认值即可跑起来。

⚠️ 安全提示：DEFAULTS 中的 ZHIHU_ACCESS_SECRET 为明文凭据。
本文件一旦提交到公开仓库，凭据即视为泄露，必须到
https://developer.zhihu.com/profile 重新生成。
正式部署请改用环境变量或密钥管理服务注入。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("TWINLOOP_ENV_FILE", str(BASE_DIR / ".env")))

# 模型凭据必须从独立的 .env.models 读取，不能被通用应用环境加载进进程。
MODEL_ENV_KEYS = {
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    "EVALUATOR_LLM_API_KEY", "EVALUATOR_LLM_BASE_URL", "EVALUATOR_LLM_MODEL",
    "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_BATCH_SIZE",
}

# --------------------------------------------------------------------------
# 内置默认配置：本地开发免配置直接启动
# --------------------------------------------------------------------------

DEFAULTS: dict[str, str] = {
    # 知乎 OAuth 应用凭证（赛事页面分配）
    "ZHIHU_OAUTH_APP_ID": "468",
    "ZHIHU_OAUTH_APP_KEY": "1edca288684b4838a8beb643b7b74a12",
    "ZHIHU_OAUTH_REDIRECT_URI": "http://127.0.0.1:8000/api/v1/sources/zhihu/callback",

    # 开放平台 Access Secret，代表本应用作为调用方
    "ZHIHU_ACCESS_SECRET": "be965dbac2e6644b9c8c0c5dbebd6022beffd664",

    # 本地 http 环境浏览器会忽略 Secure，部署到 https 后改为 true
    "TWINLOOP_COOKIE_SECURE": "false",

    # 授权完成后浏览器跳回的前端地址
    "TWINLOOP_FRONTEND_URL": "http://127.0.0.1:3000/#intro",
}


def apply_defaults() -> None:
    """把内置默认值写入 os.environ，已存在的键不覆盖。"""
    for key, value in DEFAULTS.items():
        os.environ.setdefault(key, value)


def load_env() -> bool:
    """加载配置到 os.environ。返回是否实际读到 .env 文件。

    顺序：先读 .env（若存在），再补内置默认值。
    两者都用"不覆盖已有值"策略，保证真实环境变量优先级最高。
    """
    found = False
    if ENV_FILE.exists():
        found = True
        # 只加载应用配置；模型配置由 agent.runtime.model_config 按需读取，
        # 这样即使旧 .env 中残留模型键，也不会绕过独立环境隔离。
        values: dict[str, Any] = dict(dotenv_values(ENV_FILE))
        for key, value in values.items():
            if not key or key in MODEL_ENV_KEYS or value is None or key in os.environ:
                continue
            os.environ[key] = str(value)

    # 最后补上内置默认值，确保零配置也能启动
    apply_defaults()
    return found
