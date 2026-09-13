"""契合度达标后的推送接口占位。"""
from __future__ import annotations

from typing import Protocol


class MatchPushGateway(Protocol):
    """定义推送双方知乎主页地址的接口，不绑定具体消息渠道。"""

    async def push_profile_urls(self, user_a_id: str, user_b_id: str, profile_url_a: str | None, profile_url_b: str | None, score: float) -> None:
        """推送匹配结果。"""


class NoopMatchPushGateway:
    """当前阶段的空实现，只记录最近一次推送请求，不产生外部副作用。"""

    def __init__(self) -> None:
        self.last_request: dict[str, object] | None = None

    async def push_profile_urls(self, user_a_id: str, user_b_id: str, profile_url_a: str | None, profile_url_b: str | None, score: float) -> None:
        """保存推送参数，供测试或未来接入真实渠道。"""
        self.last_request = {"user_a_id": user_a_id, "user_b_id": user_b_id, "profile_url_a": profile_url_a, "profile_url_b": profile_url_b, "score": score}

