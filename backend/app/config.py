"""应用配置。

启动时自动加载配置，无需每次手动设置环境变量。

优先级：真实环境变量 > backend/.env 文件 > 本文件内置默认值。
部署时用环境变量覆盖，本地开发直接用内置默认值即可跑起来。

⚠️ 安全提示：DEFAULTS 中的 ZHIHU_ACCESS_SECRET 为明文凭据。
本文件一旦提交到公开仓库，凭据即视为泄露，必须到
https://developer.zhihu.com/profile 重新生成。
正式部署请改用环境变量或密钥管理服务注入。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("TWINLOOP_ENV_FILE", str(BASE_DIR / ".env")))

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
    "TWINLOOP_FRONTEND_URL": "http://127.0.0.1:3000/",
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
        try:
            from dotenv import load_dotenv
            load_dotenv(ENV_FILE, override=False)
        except ImportError:
            # 未安装 python-dotenv 时退回到极简解析，保证可用
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value

    # 最后补上内置默认值，确保零配置也能启动
    apply_defaults()
    return found
