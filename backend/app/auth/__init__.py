"""认证模块：会话 Cookie、身份校验与当前用户上下文。

身份来自知乎 OAuth，本平台不维护账号密码。
知乎 Token 不进入前端和 Agent。
"""

from .router import router  # noqa: F401
