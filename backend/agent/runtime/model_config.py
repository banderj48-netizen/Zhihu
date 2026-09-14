"""独立的大模型环境配置加载器。

模型密钥、模型地址和模型名称与数据库、OAuth 等应用配置分离，默认读取
``backend/.env.models``。进程环境变量仍可覆盖文件值，便于容器和 CI 注入
短期凭据；本模块不会打印或记录任何密钥。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODEL_ENV_FILENAME = ".env.models"


def model_env_path(env_file: str | Path | None = None) -> Path:
    """返回独立模型环境文件路径；显式参数优先于进程环境变量。"""
    selected = env_file or os.getenv("TWINLOOP_MODEL_ENV_FILE")
    return Path(selected) if selected else BACKEND_ROOT / MODEL_ENV_FILENAME


def load_model_values(env_file: str | Path | None = None) -> dict[str, Any]:
    """读取独立模型环境文件，不把密钥写入全局环境变量。"""
    path = model_env_path(env_file)
    return dict(dotenv_values(path)) if path.exists() else {}


def model_setting(name: str, values: dict[str, Any], default: str | None = None) -> str | None:
    """按进程环境变量、独立模型环境文件、默认值顺序取得配置。"""
    value = os.getenv(name)
    if value is None:
        value = values.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


__all__ = ["MODEL_ENV_FILENAME", "model_env_path", "load_model_values", "model_setting"]
