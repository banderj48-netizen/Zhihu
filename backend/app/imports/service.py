"""知乎数据导入服务。

职责：调用开放平台读取授权用户数据，规范化字段后交给上层。
原始数据先由传统后端保存，再生成证据片段（见 imports/README.md）。
"""

from __future__ import annotations

from typing import Any

from . import zhihu_client


def _normalize_paging(paging: dict[str, Any] | None) -> dict[str, Any]:
    """统一分页结构。

    NextOffset 必须原样回传给下一次 Offset，不能按条数自行累加。
    服务端返回的是字符串，这里保持原值不做类型转换。
    """
    paging = paging or {}
    return {
        "is_end": paging.get("IsEnd", True),
        "next_offset": paging.get("NextOffset"),
        "totals": paging.get("Totals"),
    }


def _normalize_content_item(item: dict[str, Any]) -> dict[str, Any]:
    """规范化创作条目。

    注意：列表接口只提供 Title 与 Summary，Summary 不是正文全文。
    """
    return {
        "content_type": item.get("ContentType"),
        "url": item.get("Url"),
        "title": item.get("Title", ""),
        "summary": item.get("Summary", ""),
        "created_at": item.get("CreatedAt"),
        "like_count": item.get("LikeCount", 0),
        "comment_count": item.get("CommentCount", 0),
        "favorite_count": item.get("FavoriteCount", 0),
    }


def _normalize_followee(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "fullname": item.get("Fullname", ""),
        "url_token": item.get("UrlToken"),
        "url": item.get("Url"),
        "avatar_url": item.get("AvatarUrl", ""),
        "headline": item.get("Headline", ""),
        "follower_count": item.get("FollowerCount", 0),
    }


def _normalize_collection_item(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("Author") or {}
    return {
        "content_type": item.get("ContentType"),
        "url": item.get("Url"),
        "title": item.get("Title", ""),
        "summary": item.get("Summary", ""),
        "created_at": item.get("CreatedAt"),
        "fav_time": item.get("FavTime"),
        "like_count": item.get("LikeCount", 0),
        "author": {
            "name": author.get("Name", ""),
            "url_token": author.get("UrlToken"),
            "url": author.get("Url"),
        } if author else None,
    }


def list_contents(
    oauth_token: str, content_type: str = "all",
    limit: int = 20, offset: Any = 0,
    sort_field: str = "ts", sort_order: str = "desc",
) -> dict[str, Any]:
    data = zhihu_client.fetch_contents(
        oauth_token, content_type=content_type, limit=limit,
        offset=offset, sort_field=sort_field, sort_order=sort_order,
    )
    return {
        "content_type": content_type,
        "items": [_normalize_content_item(i) for i in (data.get("Items") or [])],
        "paging": _normalize_paging(data.get("Paging")),
        "note": "列表仅含标题与摘要，正文需跳转原文链接",
    }


def list_followees(oauth_token: str, limit: int = 20, offset: Any = 0) -> dict[str, Any]:
    data = zhihu_client.fetch_followees(oauth_token, limit=limit, offset=offset)
    return {
        "items": [_normalize_followee(i) for i in (data.get("Items") or [])],
        "paging": _normalize_paging(data.get("Paging")),
    }


def list_favlists(oauth_token: str, limit: int = 20) -> dict[str, Any]:
    data = zhihu_client.fetch_favlists(oauth_token, limit=limit)
    return {
        "items": [
            {
                "url_token": i.get("UrlToken"),
                "title": i.get("Title", ""),
                "description": i.get("Description", ""),
                "url": i.get("Url"),
                "is_public": i.get("IsPublic"),
            }
            for i in (data.get("Items") or [])
        ],
        # 收藏夹列表当前没有 Paging，服务端忽略 Offset
        "note": "收藏夹列表无分页，不保证遍历全部收藏夹",
    }


def list_favlist_contents(
    oauth_token: str, favlist_url_token: Any, limit: int = 20, offset: Any = 0
) -> dict[str, Any]:
    data = zhihu_client.fetch_favlist_contents(
        oauth_token, favlist_url_token, limit=limit, offset=offset
    )
    return {
        "items": [_normalize_collection_item(i) for i in (data.get("Items") or [])],
        "paging": _normalize_paging(data.get("Paging")),
    }


def list_recent_collections(oauth_token: str, limit: int = 20) -> dict[str, Any]:
    data = zhihu_client.fetch_collections(oauth_token, limit=limit)
    return {
        "items": [_normalize_collection_item(i) for i in (data.get("Items") or [])],
        "note": "仅为近期收藏，无分页，不等于完整收藏历史",
    }
