"""知乎数据读取路由。

所有接口都要求已登录，OAuth token 从服务端会话取出，
前端不接触也无法传入 token。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ..auth import session
from ..auth.dependencies import get_current_user
from ..auth.schemas import fail, new_request_id, ok
from . import service, zhihu_client

router = APIRouter(prefix="/api/v1/zhihu", tags=["imports"])


def _rid(request: Request) -> str:
    return request.headers.get("X-Request-Id") or new_request_id()


def _require_token(request: Request) -> str:
    """从服务端会话取出知乎 token。

    token 缺失或过期时抛错，由调用方转成 401；
    绝不降级为平台自有 Access Secret 的本人身份。
    """
    token = session.get_zhihu_token(session.read_session_id(request))
    if not token:
        raise zhihu_client.ZhihuDataError(
            "ZHIHU_TOKEN_EXPIRED", "知乎授权已过期，请重新授权", 401
        )
    return token


def _handle(request: Request, fn, *args, **kwargs) -> Any:
    rid = _rid(request)
    try:
        token = _require_token(request)
        return ok(fn(token, *args, **kwargs), rid)
    except zhihu_client.ZhihuDataError as exc:
        # 频率与配额类错误可重试，其余不可
        retryable = exc.code in {"RATE_LIMITED", "ZHIHU_SERVER_ERROR", "NETWORK_ERROR"}
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(exc.code, exc.message, rid, retryable),
        )


@router.get("/contents")
async def contents(
    request: Request,
    type: str = Query(default="all", description="all/answer/article/zvideo/pin/question"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: str = Query(default="0", description="首次传 0，翻页时原样回传 next_offset"),
    sort: str = Query(default="ts", description="ts 或 like_count"),
    order: str = Query(default="desc", description="desc 或 asc"),
    user=Depends(get_current_user),
):
    """读取当前用户的创作列表（回答、文章等）。"""
    return _handle(request, service.list_contents,
                   content_type=type, limit=limit, offset=offset,
                   sort_field=sort, sort_order=order)


@router.get("/followees")
async def followees(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    offset: str = Query(default="0"),
    user=Depends(get_current_user),
):
    """读取当前用户的关注列表。"""
    return _handle(request, service.list_followees, limit=limit, offset=offset)


@router.get("/favlists")
async def favlists(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(get_current_user),
):
    """读取当前用户的收藏夹列表。"""
    return _handle(request, service.list_favlists, limit=limit)


@router.get("/favlists/{url_token}/contents")
async def favlist_contents(
    url_token: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    offset: str = Query(default="0"),
    user=Depends(get_current_user),
):
    """读取指定收藏夹中的内容。url_token 来自 /favlists。"""
    return _handle(request, service.list_favlist_contents,
                   favlist_url_token=url_token, limit=limit, offset=offset)


@router.get("/collections")
async def collections(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(get_current_user),
):
    """读取近期收藏。无分页。"""
    return _handle(request, service.list_recent_collections, limit=limit)
