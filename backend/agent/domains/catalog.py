"""Versioned, searchable domain catalogue used by the Agent boundary.

The catalogue deliberately keeps interest and self-reported expertise as
separate selections.  Selecting a topic never creates a verified capability.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

CATALOG_VERSION = "domains-2026-01"

@dataclass(frozen=True)
class DomainNode:
    id: str
    label: str
    parent_id: str | None
    level: str
    aliases: tuple[str, ...] = ()
    description: str = ""

_GROUPS: dict[str, tuple[str, ...]] = {
    "computer": ("编程语言与软件工程", "算法与数据结构", "人工智能与机器学习", "数据工程与数据库", "网络与分布式系统", "信息安全与隐私", "操作系统与硬件", "人机交互与产品"),
    "engineering": ("电子与通信工程", "机械与自动化", "土木与建筑", "能源与环境工程", "材料与化工", "航空航天与交通"),
    "math_science": ("数学与统计", "物理", "化学", "生物与生命科学", "地球科学与气候", "天文与空间科学"),
    "medicine": ("基础医学", "临床医学", "公共卫生", "心理健康", "营养与运动医学", "医药与医疗技术"),
    "business": ("经济学", "金融与投资", "会计与税务", "管理与组织", "市场营销与品牌", "创业与商业模式", "供应链与运营"),
    "law_policy": ("法律实务", "公共政策", "国际关系", "政治制度", "社会治理", "知识产权与科技治理"),
    "social": ("社会学", "心理学研究", "教育学", "传播学", "人口与城市研究", "人类学"),
    "humanities": ("历史", "哲学", "语言学", "文学与写作", "宗教与思想史", "考古与博物馆"),
    "arts": ("视觉艺术", "平面与交互设计", "影视与摄影", "音乐与作曲", "舞蹈与戏剧", "工艺与时尚"),
    "media": ("新闻与事实核查", "出版与编辑", "内容创作", "游戏设计", "网络社区与平台"),
    "career": ("求职与面试", "职业发展", "项目与团队协作", "领导力", "学习方法", "自由职业"),
    "life": ("个人财务", "居住与家务", "消费与购物", "饮食烹饪", "旅行与户外", "亲子与家庭"),
    "relationship": ("亲密关系", "友谊与社交", "沟通与冲突", "职场关系", "个人边界", "照护与支持"),
    "sports": ("跑步与耐力", "力量与体能", "球类运动", "水上与冰雪运动", "武术与格斗", "运动观赛"),
    "entertainment": ("电影与剧集", "动漫与漫画", "阅读", "音乐欣赏", "旅行体验", "桌游与电子游戏"),
    "sustainability": ("生态与保护", "气候行动", "可持续城市", "农业与食品系统", "公益与志愿服务"),
    "belief_values": ("伦理与道德", "科学与证据", "审美与价值", "人生意义", "宗教与信仰"),
    "methods": ("批判性思维", "研究设计", "数据分析", "决策与风险", "谈判与说服", "信息检索"),
}

_ROOT_LABELS = {
    "computer":"计算机与信息技术", "engineering":"工程与制造", "math_science":"自然科学与数学", "medicine":"医疗、健康与心理", "business":"商业、经济与金融", "law_policy":"法律、政治与公共治理", "social":"社会科学与教育", "humanities":"人文、历史与思想", "arts":"艺术、设计与创作", "media":"媒体、内容与平台", "career":"职业、组织与学习", "life":"生活、家庭与消费", "relationship":"关系、沟通与社交", "sports":"体育、身体与户外", "entertainment":"文化、娱乐与游戏", "sustainability":"环境、农业与可持续发展", "belief_values":"价值、伦理与信念", "methods":"通用方法与认知工具",
}

def _build() -> tuple[DomainNode, ...]:
    out: list[DomainNode] = []
    for gid, categories in _GROUPS.items():
        out.append(DomainNode(gid, _ROOT_LABELS[gid], None, "root"))
        for ci, label in enumerate(categories, 1):
            cid = f"{gid}.{ci:02d}"
            out.append(DomainNode(cid, label, gid, "category"))
            # Leaves make selection concrete while keeping the catalogue easy to revise.
            for li, suffix in enumerate(("基础概念", "实践与案例", "前沿进展", "争议与政策", "工具与资源"), 1):
                out.append(DomainNode(f"{cid}.{li:02d}", f"{label}·{suffix}", cid, "leaf", (label,)))
    return tuple(out)

CATALOG = _build()
BY_ID = {n.id: n for n in CATALOG}

def search(query: str | None = None, parent_id: str | None = None, level: str | None = None) -> list[dict]:
    q = (query or "").strip().casefold()
    nodes = [n for n in CATALOG if (parent_id is None or n.parent_id == parent_id) and (level is None or n.level == level)]
    if q:
        nodes = [n for n in nodes if q in (n.label + " " + " ".join(n.aliases)).casefold()]
    return [asdict(n) for n in nodes]

def get(node_id: str) -> dict | None:
    node = BY_ID.get(node_id)
    return asdict(node) if node else None
