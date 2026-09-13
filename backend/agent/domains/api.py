from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .catalog import CATALOG_VERSION, get, search, BY_ID
from .repository import get_selections, replace_selections
from agent.adapters.zhihu import search_domain

router = APIRouter(prefix="/v1/domains", tags=["domains"])
class SelectionPayload(BaseModel):
    expected_revision: int = Field(default=0, ge=0)
    interests: list[dict] = Field(default_factory=list)
    expertise: list[dict] = Field(default_factory=list)
@router.get("")
def list_domains(q: str | None = None, parent_id: str | None = None, level: str | None = None):
    return {"catalog_version": CATALOG_VERSION, "items": search(q, parent_id, level)}
@router.get("/selections/me")
def my_selections(x_user_id: str | None = Header(default=None)):
    return get_selections(x_user_id or "local-demo-user")
@router.put("/selections/me")
def put_selections(body: SelectionPayload, x_user_id: str | None = Header(default=None)):
    try: return replace_selections(x_user_id or "local-demo-user", body.model_dump())
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
@router.post("/{domain_id}/research")
def research_domain(domain_id: str, count: int = 8):
    node = BY_ID.get(domain_id)
    if node is None or node.level == "root": raise HTTPException(404, "请选择分类或叶子领域")
    try: return {"domain_id": domain_id, "items": search_domain(node, count)}
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(503, str(exc)) from exc
@router.get("/{domain_id}")
def domain_detail(domain_id: str):
    value = get(domain_id)
    if value is None: raise HTTPException(404, "领域不存在")
    return {"catalog_version": CATALOG_VERSION, "item": value}
