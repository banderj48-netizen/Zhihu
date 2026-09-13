"""生成 TwinLoop 项目的中文接口文档和项目说明 PDF。

本脚本只读取项目代码中已经存在的接口和数据结构，不连接数据库，也不调用外部服务。
生成结果位于 output/pdf/，便于前端和产品同学直接查阅。
"""
from __future__ import annotations

import html
import textwrap
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf"
FONT = Path("C:/Windows/Fonts/Deng.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/Dengb.ttf")


def register_fonts() -> None:
    """注册中文字体，避免 PDF 中出现方框或乱码。"""
    pdfmetrics.registerFont(TTFont("TwinSans", str(FONT)))
    pdfmetrics.registerFont(TTFont("TwinSans-Bold", str(FONT_BOLD)))


def esc(value: object) -> str:
    """转义 Paragraph 中的 HTML 特殊字符。"""
    return html.escape(str(value), quote=False)


def make_styles() -> dict[str, ParagraphStyle]:
    """创建统一的标题、正文、表格和代码样式。"""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="TwinSans-Bold", fontSize=24, leading=32, alignment=TA_CENTER, textColor=colors.HexColor("#17324D"), spaceAfter=10 * mm),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="TwinSans", fontSize=11, leading=17, alignment=TA_CENTER, textColor=colors.HexColor("#5B6B7A"), spaceAfter=8 * mm),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="TwinSans-Bold", fontSize=16, leading=23, textColor=colors.HexColor("#17324D"), spaceBefore=7 * mm, spaceAfter=3 * mm),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="TwinSans-Bold", fontSize=12.5, leading=19, textColor=colors.HexColor("#22577A"), spaceBefore=4 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="TwinSans", fontSize=9.3, leading=15, textColor=colors.HexColor("#263238"), spaceAfter=2.2 * mm),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="TwinSans", fontSize=8, leading=12, textColor=colors.HexColor("#52616B"), spaceAfter=1.5 * mm),
        "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontName="TwinSans", fontSize=9.2, leading=14, leftIndent=5 * mm, firstLineIndent=-3 * mm, bulletIndent=1 * mm, spaceAfter=1.2 * mm),
        "table": ParagraphStyle("table", parent=base["BodyText"], fontName="TwinSans", fontSize=7.6, leading=10.5, textColor=colors.HexColor("#263238")),
        "table_head": ParagraphStyle("table_head", parent=base["BodyText"], fontName="TwinSans-Bold", fontSize=7.8, leading=10.5, textColor=colors.white),
        "code": ParagraphStyle("code", parent=base["Code"], fontName="TwinSans", fontSize=7.4, leading=10.5, leftIndent=3 * mm, rightIndent=3 * mm, backColor=colors.HexColor("#F4F7F9"), borderColor=colors.HexColor("#D9E2E8"), borderWidth=0.5, borderPadding=3 * mm, spaceBefore=1.5 * mm, spaceAfter=3 * mm),
        "note": ParagraphStyle("note", parent=base["BodyText"], fontName="TwinSans", fontSize=8.6, leading=13.5, leftIndent=4 * mm, rightIndent=3 * mm, borderColor=colors.HexColor("#B9D6E8"), borderWidth=0.6, borderPadding=3 * mm, backColor=colors.HexColor("#F1F8FC"), spaceBefore=2 * mm, spaceAfter=3 * mm),
    }


def P(text: object, style: ParagraphStyle) -> Paragraph:
    """创建转义后的段落。"""
    return Paragraph(esc(text).replace("\n", "<br/>"), style)


def rich(text: str, style: ParagraphStyle) -> Paragraph:
    """创建允许少量安全 HTML 标签的段落。"""
    return Paragraph(text, style)


def bullets(items: list[str], styles: dict[str, ParagraphStyle]) -> list[Paragraph]:
    """生成中文项目符号列表。"""
    return [Paragraph(f"• {esc(item)}", styles["bullet"]) for item in items]


def code(text: str, styles: dict[str, ParagraphStyle]) -> Preformatted:
    """生成等宽代码块。"""
    # Preformatted 不会自动换行，手动折行避免长 JSON 超出页面边界。
    lines: list[str] = []
    for line in text.splitlines():
        lines.extend(textwrap.wrap(line, width=72, subsequent_indent="  ", break_long_words=True, break_on_hyphens=False) or [""])
    return Preformatted("\n".join(lines), styles["code"])


def table(data: list[list[object]], widths: list[float], styles: dict[str, ParagraphStyle], header: bool = True) -> Table:
    """生成带中文表头和交替底色的表格。"""
    converted: list[list[object]] = []
    for row_index, row in enumerate(data):
        converted.append([x if isinstance(x, (Paragraph, Table)) else P(x, styles["table_head"] if header and row_index == 0 else styles["table"]) for x in row])
    t = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        commands += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#22577A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    for i in range(1 if header else 0, len(data)):
        if i % 2 == 0:
            commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F7FAFB")))
    t.setStyle(TableStyle(commands))
    return t


class NumberedDocTemplate(BaseDocTemplate):
    """带页眉、页脚和页码的 PDF 模板。"""

    def __init__(self, filename: str, document_title: str) -> None:
        super().__init__(filename, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=18 * mm, bottomMargin=16 * mm, title=document_title, author="TwinLoop")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=self._draw_header_footer)])

    def _draw_header_footer(self, canvas, doc) -> None:
        """绘制统一页眉、页脚和页码。"""
        canvas.saveState()
        canvas.setFont("TwinSans", 7.5)
        canvas.setFillColor(colors.HexColor("#7A8A96"))
        canvas.drawString(self.leftMargin, A4[1] - 11 * mm, "TwinLoop 数字分身项目")
        canvas.drawRightString(A4[0] - self.rightMargin, 9 * mm, f"第 {doc.page} 页")
        canvas.setStrokeColor(colors.HexColor("#D9E2E8"))
        canvas.line(self.leftMargin, A4[1] - 13 * mm, A4[0] - self.rightMargin, A4[1] - 13 * mm)
        canvas.restoreState()


def endpoint(story: list, styles: dict[str, ParagraphStyle], method: str, path: str, purpose: str, auth: str, params: str, request: str, response: str, notes: str = "") -> None:
    """向接口文档追加一个完整接口条目。"""
    story.append(rich(f"<b>{esc(method)} {esc(path)}</b>", styles["h2"]))
    story.append(P(purpose, styles["body"]))
    story.append(table([["项目", "说明"], ["是否需要登录", auth], ["请求参数", params]], [34 * mm, 132 * mm], styles))
    if request:
        story.append(P("请求示例", styles["small"]))
        story.append(code(request, styles))
    story.append(P("响应示例", styles["small"]))
    story.append(code(response, styles))
    if notes:
        story.append(rich(f"<b>前端提示：</b>{esc(notes)}", styles["note"]))


def build_api_pdf(path: Path) -> None:
    """生成后端接口参考文档。"""
    styles = make_styles()
    story: list = [P("TwinLoop 后端接口文档", styles["title"]), P(f"面向前端设计与联调 | 代码盘点日期：{date.today().isoformat()}", styles["subtitle"]), HRFlowable(width="100%", thickness=1, color=colors.HexColor("#4F90B5")), Spacer(1, 5 * mm)]
    story.append(P("这份文档把当前仓库中已经写出的 FastAPI 接口按功能分类，逐一说明用途、参数和返回值。没有编程经验也可以按照“请求地址 + 参数 + 示例”理解；前端开发时优先使用本文件中标注为“已实现”的 HTTP 接口。", styles["body"]))
    story.append(rich("<b>阅读方法：</b>先看公共约定，再按登录、知乎资料、画像初始化、性格测评、领域选择和聊天记录的顺序阅读。所有地址都假定后端服务运行在同一域名下。", styles["note"]))

    story.append(P("1. 公共约定", styles["h1"]))
    story.append(P("请求头", styles["h2"]))
    story.append(table([["请求头", "是否必须", "用途"], ["Cookie: twinloop_session", "正式登录接口必须", "知乎 OAuth 登录成功后由后端设置，前端无需读取内容。"], ["X-Request-Id", "写请求建议传", "用于排查问题；不传时后端生成。"], ["X-User-Id", "本地演示接口使用", "旧版演示接口和 runtime 查询接口用它识别当前用户。生产登录优先使用 HttpOnly Cookie。"]], [39 * mm, 30 * mm, 97 * mm], styles))
    story.append(P("响应格式有两种：认证、知乎授权和知乎数据接口通常返回统一包装；早期画像演示接口和 runtime 接口直接返回 JSON。", styles["body"]))
    story.append(code('''统一成功响应\n{\n  "request_id": "req_xxx",\n  "data": { ... }\n}\n\n统一失败响应\n{\n  "request_id": "req_xxx",\n  "error": {\n    "code": "ERROR_CODE",\n    "message": "给用户看的说明",\n    "retryable": false\n  }\n}''', styles))

    story.append(P("2. 登录、授权与系统状态", styles["h1"]))
    endpoint(story, styles, "GET", "/health", "检查后端是否启动。适合前端进入页面时做连通性检查。", "不需要", "无", "", '{"ok": true, "service": "twinloop-api", "time": "2026-09-14T...+00:00"}')
    endpoint(story, styles, "POST", "/api/v1/sources/zhihu/connect", "创建知乎授权地址。前端拿到 authorization_url 后跳转浏览器。", "不需要", "body.scopes: 字符串数组，可选，默认 [profile, answers]；body.request_id 可选。", '{"scopes": ["profile", "answers"], "request_id": "req_demo"}', '{"request_id":"req_demo","data":{"authorization_url":"https://www.zhihu.com/oauth/...","state_id":"state_xxx"}}', "不要把 authorization_url 改写成普通接口请求，应该让浏览器直接跳转。")
    endpoint(story, styles, "GET", "/api/v1/sources/zhihu/callback", "知乎授权回调。通常由知乎服务器跳回，不由前端主动调用。", "需要 OAuth state，不需要前端登录 Cookie", "查询参数 authorization_code 或 code（二选一）、state。", "浏览器访问 /api/v1/sources/zhihu/callback?authorization_code=...&state=...", "成功时 302 跳转到前端地址，并设置 HttpOnly 会话 Cookie；失败时返回统一 error。", "前端只需要在回跳后的页面调用 /api/v1/me。")
    endpoint(story, styles, "GET", "/api/v1/me", "读取当前登录用户、知乎连接状态和数字分身状态。", "需要登录 Cookie", "无", "", '{"request_id":"req_xxx","data":{"user_id":"zhihu_123","avatar_id":null,"avatar_status":"not_created","zhihu_connected":true,"zhihu":{"fullname":"小明","avatar_url":"https://...","headline":"后端工程师"}}}')
    endpoint(story, styles, "POST", "/api/v1/auth/logout", "退出当前平台登录。只清除本地会话，不撤销知乎授权。", "不登录也可调用，接口幂等", "body.request_id 可选。", '{"request_id":"req_logout"}', '{"request_id":"req_logout","data":{"logged_out":true}}')
    endpoint(story, styles, "GET", "/v1/me", "旧版演示接口：读取内存中的画像状态。前端新页面不建议依赖它。", "通过 X-User-Id 识别", "请求头 X-User-Id，可省略，默认 local-demo-user。", "X-User-Id: user_123", '{"user_id":"user_123","twin":{"status":"not_started","revision":null}}', "这是兼容旧原型的直接 JSON 接口，与 /api/v1/me 的正式登录响应不同。")

    story.append(P("3. 知乎资料读取", styles["h1"]))
    story.append(P("下面接口都要求已经完成知乎授权。知乎 access token 只保存在服务端会话中，前端不能也不应该把 token 放进请求。", styles["body"]))
    endpoint(story, styles, "GET", "/api/v1/zhihu/contents", "读取当前用户的回答、文章、视频、想法或问题列表。", "需要登录和有效知乎授权", "type=all/answer/article/zvideo/pin/question；limit 1-50，默认20；offset 翻页游标；sort=ts 或 like_count；order=desc 或 asc。", "?type=answer&limit=20&offset=0&sort=ts&order=desc", '{"request_id":"req_xxx","data":{"items":[{"id":"...","title":"...","content":"..."}],"next_offset":"20"}}', "首次 offset 传 0，后续把响应中的 next_offset 原样带回。")
    endpoint(story, styles, "GET", "/api/v1/zhihu/followees", "读取当前用户关注的人。", "需要登录和有效知乎授权", "limit 1-50，默认20；offset 默认0。", "?limit=20&offset=0", '{"request_id":"req_xxx","data":{"items":[{"id":"...","name":"..."}],"next_offset":"20"}}')
    endpoint(story, styles, "GET", "/api/v1/zhihu/favlists", "读取当前用户收藏夹列表。", "需要登录和有效知乎授权", "limit 1-50，默认20。", "?limit=20", '{"request_id":"req_xxx","data":{"items":[{"url_token":"tech","title":"技术收藏","item_count":12}]}}')
    endpoint(story, styles, "GET", "/api/v1/zhihu/favlists/{url_token}/contents", "读取指定收藏夹中的内容。url_token 来自收藏夹列表。", "需要登录和有效知乎授权", "路径参数 url_token；limit 1-50；offset 默认0。", " /api/v1/zhihu/favlists/tech/contents?limit=20&offset=0", '{"request_id":"req_xxx","data":{"items":[{"id":"...","title":"..."}],"next_offset":"20"}}')
    endpoint(story, styles, "GET", "/api/v1/zhihu/collections", "读取近期收藏。当前接口无分页。", "需要登录和有效知乎授权", "limit 1-50，默认20。", "?limit=20", '{"request_id":"req_xxx","data":{"items":[{"id":"...","title":"...","created_at":"..."}]}}')

    story.append(P("4. 领域目录与选择", styles["h1"]))
    endpoint(story, styles, "GET", "/v1/domains", "读取领域目录，也可按关键词、父级或层级筛选。", "当前通过 X-User-Id 兼容调用", "q 关键词；parent_id 父级 ID；level=root/category/leaf。", "?q=人工智能&level=leaf", '{"catalog_version":"domains-2026-01","items":[{"id":"computer.03.01","label":"人工智能与机器学习·基础概念","parent_id":"computer.03","level":"leaf","aliases":["人工智能与机器学习"],"description":""}]}')
    endpoint(story, styles, "GET", "/v1/domains/selections/me", "读取当前用户已选择的兴趣和擅长领域。", "通过 X-User-Id", "无", "X-User-Id: user_123", '{"catalog_version":"domains-2026-01","revision":1,"interests":[{"domain_id":"computer.03.01","interest_level":3,"proficiency":null}],"expertise":[]}')
    endpoint(story, styles, "PUT", "/v1/domains/selections/me", "整体替换兴趣和擅长领域选择。", "通过 X-User-Id", "expected_revision；interests[]；expertise[]。interest_level 为0-3；proficiency 可为 novice/familiar/working/advanced/unknown。", '{"expected_revision":0,"interests":[{"domain_id":"computer.03.01","interest_level":3}],"expertise":[{"domain_id":"computer.05.02","interest_level":2,"proficiency":"advanced","notes":"熟悉分布式系统"}]}', '{"catalog_version":"domains-2026-01","revision":1,"interests":[...],"expertise":[...]}', "这是整体替换而不是单项追加；revision 不一致会返回 409。")
    endpoint(story, styles, "GET", "/v1/domains/{domain_id}", "读取一个领域节点的详情。", "不需要登录", "路径参数 domain_id。", "/v1/domains/computer.03", '{"catalog_version":"domains-2026-01","item":{"id":"computer.03","label":"人工智能与机器学习","level":"category",...}}')
    endpoint(story, styles, "POST", "/v1/domains/{domain_id}/research", "根据领域查询知乎专业问题或争议问题，供观点题生成使用。", "不需要登录（当前代码）", "路径参数 domain_id；count 默认8。", " /v1/domains/computer.03/research?count=8", '{"domain_id":"computer.03","items":[{"question_id":"...","title":"AI 会取代程序员吗？","summary":"..."}]}', "生产环境建议在路由层增加登录校验。")

    story.append(P("5. 性格测评", styles["h1"]))
    endpoint(story, styles, "GET", "/v1/personality/questions", "获取 Big Five/IPIP 50 题问卷。", "不需要登录（当前代码）", "无", "", '{"instrument_version":"ipip-big-five-50-zh-v1","model":"big_five","scale":{"min":1,"max":5,"labels":["非常不符合","较不符合","一般","较符合","非常符合"]},"items":[{"id":"E01","text":"我是聚会中活跃的人。"}]}')
    endpoint(story, styles, "POST", "/v1/personality/assessments", "提交性格测评答案并保存结果。", "通过 X-User-Id", "answers 为题目 ID 到1-5整数的映射；notes 可选；request_key 可选，用于幂等。", '{"answers":{"E01":4,"E02":5,"A01":3},"notes":"第一次测评","request_key":"assessment-submit-1"}', '{"assessment_id":"assessment_xxx","status":"partial","scores":{"extraversion":7.5,"agreeableness":5.0},"confidence":0.15,"style_tags":["主动社交"]}', "完整 50 题且无明显直线作答时状态为 completed；答案非法返回 422。")
    endpoint(story, styles, "POST", "/v1/personality/skip", "跳过性格测评，写入低置信度的 skipped 结果。", "通过 X-User-Id", "request_key 可选。", '{"request_key":"skip-1"}', '{"assessment_id":"assessment_xxx","status":"skipped","confidence":0.0,"scores":{"extraversion":null,"agreeableness":null,"conscientiousness":null,"neuroticism":null,"openness":null}}')
    endpoint(story, styles, "GET", "/v1/personality/assessments/latest", "读取当前用户最近一次性格测评。", "通过 X-User-Id", "无", "X-User-Id: user_123", '{"assessment_id":"assessment_xxx","status":"completed","scores":{"extraversion":6.8,...},"confidence":0.84}')

    story.append(P("6. 画像读取、修改与版本", styles["h1"]))
    endpoint(story, styles, "GET", "/v1/twin/profile", "读取当前用户的原型画像。", "通过 X-User-Id", "无", "X-User-Id: user_123", '{"revision":1,"status":"draft","data":{"facts":[],"domains":[],"stances":[],"style":{},"memories":[],"personality":{...}},"evidence":[]}')
    endpoint(story, styles, "PATCH", "/v1/twin/profile", "修改原型画像中的 data 字段。", "通过 X-User-Id", "body.data 为要合并的字段。", '{"data":{"facts":["后端工程师"],"style":{"tone":["直接"]}}}', '{"revision":2,"status":"draft","data":{"facts":["后端工程师"],"style":{"tone":["直接"]},...}}', "这是旧原型内存画像接口；正式 UUID 画像应通过 ProfileRepository 和版本机制写入。")
    endpoint(story, styles, "POST", "/v1/twin/versions", "发布当前原型画像为一个版本。", "通过 X-User-Id", "expected_revision，默认0。", '{"expected_revision":2}', '{"id":"version_xxx","user_id":"user_123","revision":2,"created_at":"...","card":{"spec":"chara_card_v2",...}}', "revision 不一致返回 409，前端应先重新 GET profile。")
    endpoint(story, styles, "GET", "/v1/twin/versions/{vid}", "读取指定画像版本。", "通过 X-User-Id", "路径参数 vid。", "/v1/twin/versions/version_xxx", '{"id":"version_xxx","user_id":"user_123","revision":2,"card":{"spec":"chara_card_v2",...}}')

    story.append(P("7. 数字分身初始化与心灵感应题", styles["h1"]))
    story.append(P("这些接口位于 runtime API，当前使用 X-User-Id 识别用户。初始化会话把性格、领域、观点题和社交题结果暂存在数据库，完成时调用 ProfileRepository 创建初始画像。", styles["body"]))
    endpoint(story, styles, "POST", "/v1/twin/initializations", "创建或恢复当前用户唯一的初始化会话。", "通过 X-User-Id", "import_job_id 可选。", '{"import_job_id":"job_xxx"}', '{"id":"session_xxx","user_id":"user_123","status":"importing","current_step":"importing","input_data":{},"generated_profile":{}}', "同一用户重复调用不会创建第二个会话。")
    endpoint(story, styles, "GET", "/v1/twin/initializations/{session_id}", "查询初始化进度和已保存输入。", "当前代码未在路由层校验用户归属，前端应只访问自己的 session_id", "路径参数 session_id。", "/v1/twin/initializations/session_xxx", '{"id":"session_xxx","status":"domain_pending","current_step":"domains","input_data":{"personality":{...},"domains":{...}}}')
    endpoint(story, styles, "POST", "/v1/twin/initializations/{session_id}/{step}", "保存 personality、domains、opinion-answers 或 social-answers 步骤。", "当前代码未在路由层校验用户归属", "路径参数 session_id、step；body.data 为步骤数据。", '{"data":{"answers":{"E01":4},"notes":"..."}}', '{"id":"session_xxx","status":"personality_pending","current_step":"personality","input_data":{"personality":{"answers":{"E01":4}}}}', "前端应按初始化流程顺序提交，非法 session 返回 404。")
    endpoint(story, styles, "POST", "/v1/twin/initializations/{session_id}/complete", "用基础身份和已保存结果创建初始画像。", "当前代码未在路由层校验用户归属", "body.identity 可包含 display_name、summary、occupation、location、age、privacy_level、extra。", '{"identity":{"display_name":"小明","summary":"后端工程师","occupation":"软件工程师","privacy_level":"private"}}', '{"avatar_id":"...","version_id":"...","version_no":1,"status":"initialized"}', "当前生成器主要复用测评和用户输入；知乎资料、LLM 提炼的完整闭环仍需后续接入。")
    endpoint(story, styles, "POST", "/v1/twin/mind-reading/{dialogue_run_id}", "保存一条对话后待用户选择的心灵感应题。", "通过 X-User-Id", "body.avatar_id 必须提供；其余题干、选项和 agent_option_id 放在 body。", '{"avatar_id":"avatar_b","question":"遇到反例时会怎么做？","options":[{"id":"a","text":"修正观点"},{"id":"b","text":"坚持原观点"}],"agent_option_id":"a"}', '{"id":"feedback_xxx","question":{...},"status":"pending"}')
    endpoint(story, styles, "POST", "/v1/twin/mind-reading/{question_id}/answer", "提交心灵感应题选择。", "当前代码未在路由层校验用户归属", "body.option_id。", '{"option_id":"a"}', '{"id":"feedback_xxx","is_match":true,"status":"answered"}')

    story.append(P("8. Agent 聊天组查询", styles["h1"]))
    story.append(P("聊天组是一次双 Agent 对话函数调用的索引；完整正文仍来自 chat_messages。用户只要是发起方或被邀请方，就能看到这一组。", styles["body"]))
    endpoint(story, styles, "GET", "/v1/twin/chat-groups/count", "统计当前用户参与的聊天组数量。", "通过 X-User-Id", "status 可选，例如 completed/running/failed。", "?status=completed", '{"count":12}')
    endpoint(story, styles, "GET", "/v1/twin/chat-groups", "分页列出当前用户参与的聊天组和双方基础信息。", "通过 X-User-Id", "page 从1开始；page_size 1-100，默认20；status 可选。", "?page=1&page_size=20&status=completed", '{"items":[{"chat_no":"chat_xxx","dialogue_run_id":"run_xxx","conversation_id":"conv_xxx","initiator":{"user_id":"u1","avatar_id":"a1","display_name":"Agent A"},"invited":{"user_id":"u2","avatar_id":"a2","display_name":"Agent B"},"status":"completed","started_at":"...","ended_at":"...","message_count":12}],"page":1,"page_size":20,"total":35}')
    endpoint(story, styles, "GET", "/v1/twin/chat-groups/{chat_no}/messages", "按顺序读取一组聊天的完整消息。", "通过 X-User-Id，必须是发起方或被邀请方", "路径参数 chat_no。软删除消息不会返回。", "/v1/twin/chat-groups/chat_abc/messages", '{"chat_no":"chat_abc","dialogue_run_id":"run_xxx","conversation_id":"conv_xxx","status":"completed","initiator":{"user_id":"u1","avatar_id":"a1","display_name":"Agent A"},"invited":{"user_id":"u2","avatar_id":"a2","display_name":"Agent B"},"messages":[{"message_id":"m1","sequence_no":1,"sender_avatar_id":"a1","sender_name":"Agent A","content":"你好","message_type":"text","sent_at":"...","metadata":{}}]}', "非参与用户和不存在的 chat_no 都返回 404，避免泄露记录是否存在。")

    story.append(PageBreak())
    story.append(P("9. 供业务代码调用、但不是 HTTP 接口的函数", styles["h1"]))
    story.append(P("下面函数是后端内部能力，前端不能直接访问。它们由服务端编排流程调用，也不会自动暴露给 Agent。", styles["body"]))
    story.append(table([["函数", "作用", "前端是否直接调用"], ["build_context(user_id, question, ...)", "固定画像直查 PostgreSQL，长内容用 PostgreSQL 关键词 + Chroma 混合检索，组装结构化上下文。", "否"], ["run_agent_dialogue(...)", "运行一次双 Agent 交替对话，写入 chat_messages、agent_dialogue_runs 和 agent_chat_groups。", "否；当前需由业务服务触发"], ["create_behavior_memory_tool(...)", "绑定 user_id/avatar_id 的行为记忆 LangGraph 工具。", "否"], ["InitializationService.complete(...)", "使用已保存初始化数据创建初始画像。", "通过 HTTP 初始化接口间接调用"], ["ChatGroupService.*", "查询聊天组数量、列表和完整消息。", "通过 HTTP 聊天组接口间接调用"]], [59 * mm, 87 * mm, 30 * mm], styles))

    story.append(P("10. 常见错误与前端处理", styles["h1"]))
    story.extend(bullets(["401：未登录、会话无效或知乎授权过期。引导用户重新授权。", "404：资源不存在或用户无权访问。聊天详情接口故意统一返回 404，前端不要区分“不存在”和“无权限”。", "409：revision 冲突。重新读取最新 profile 或领域选择后再提交。", "422：请求参数格式不合法，例如题目答案不在1-5、领域 ID 不可选。", "429/5xx：知乎频率限制、网络错误或服务暂时不可用；只有 error.retryable=true 时才自动重试。"], styles))
    story.append(P("11. 当前实现边界", styles["h1"]))
    story.extend(bullets(["当前仓库已经提供聊天组查询接口，但没有单独的 HTTP POST /dialogues 路由；启动双 Agent 对话仍需由业务代码调用 run_agent_dialogue。", "runtime 初始化接口的部分路由目前缺少用户归属校验，前端必须保存并只使用当前用户自己的 session_id。", "正式 OAuth 接口使用 HttpOnly Cookie；/v1/* 原型接口依赖 X-User-Id，二者不要混用为同一种生产认证方案。", "接口返回结构以当前代码为准；如果后端后续统一响应包装，前端应以版本号或 OpenAPI 文档更新为准。"], styles))
    NumberedDocTemplate(str(path), "TwinLoop 后端接口文档").build(story)


def build_project_pdf(path: Path) -> None:
    """生成项目原理、用户流程和数据库说明 PDF。"""
    styles = make_styles()
    story: list = [P("TwinLoop 数字分身项目说明", styles["title"]), P(f"实现原理、用户体验流程与数据库执行指南 | {date.today().isoformat()}", styles["subtitle"]), HRFlowable(width="100%", thickness=1, color=colors.HexColor("#4F90B5")), Spacer(1, 5 * mm)]
    story.append(P("TwinLoop 的目标是：用户用知乎账号登录后，通过知乎内容、性格测评、兴趣和专长选择、观点题与社交情景题，逐步生成一个“有证据、可追溯、会成长”的数字分身；随后让不同用户的数字分身在受控场景中进行对话，并把结果反馈给用户。", styles["body"]))
    story.append(rich("<b>奥卡姆剃刀原则：</b>已有模块能完成的能力直接复用，不重复创建第二套知乎客户端、性格评分器、画像仓储或聊天正文表。", styles["note"]))

    story.append(P("1. 系统总体原理", styles["h1"]))
    story.append(code('''知乎 OAuth 登录\n      ↓\n用户与唯一数字分身\n      ↓\n原始知乎资料 + 性格测评 + 领域选择 + 两类情景题\n      ↓\nProfileRepository 生成版本化画像\n      ↓\n每轮对话：固定画像直查 + 动态记忆混合检索\n      ↓\nLangGraph 驱动 Agent A / Agent B\n      ↓\nPostgreSQL 保存事实，Chroma 保存向量索引\n      ↓\n评判模型评分、心灵感应反馈和画像成长''', styles))
    story.append(P("系统分成四层：", styles["body"]))
    story.extend(bullets(["接入层：知乎 OAuth、会话 Cookie、知乎资料读取。", "画像层：基础身份、性格、兴趣、专长、观点、行为记忆、表达风格、安全策略和版本。", "运行层：LangGraph Agent、工具调用、双 Agent 对话、并发限制、评判模型。", "数据层：PostgreSQL 是事实源；Chroma 只保存向量和最小元数据，不能替代权限和正文。"], styles))

    story.append(P("2. 用户体验流程", styles["h1"]))
    story.append(P("阶段一：登录知乎", styles["h2"]))
    story.extend(bullets(["前端调用 POST /api/v1/sources/zhihu/connect。", "浏览器跳转 authorization_url，用户在知乎确认授权。", "知乎回调后端 callback；后端校验 state、换取 token、按知乎 uid 建档，并设置 HttpOnly Cookie。", "前端回到页面后调用 GET /api/v1/me，判断 zhihu_connected 和 avatar_status。"], styles))
    story.append(P("阶段二：初始化数字分身", styles["h2"]))
    story.extend(bullets(["创建初始化会话，记录 import_job_id。", "读取用户授权范围内的回答、文章和帖子，并保存原始资料。", "展示 Big Five 性格测评；用户可完整作答或跳过。", "用户选择兴趣和擅长领域；后端通过领域目录保证 ID 合法。", "根据领域读取知乎专业问题和争议问题，生成观点选择题。", "展示限时现实社交情景题，记录选项和耗时。", "用户填写基础身份，系统把上述结果转换为画像候选，创建第一个 active 版本。"], styles))
    story.append(P("阶段三：进入 Agent 社交场景", styles["h2"]))
    story.extend(bullets(["用户选择场景和匹配方式：LLM 匹配、随机匹配或手动指定。", "发起方 Agent A 与被邀请方 Agent B 绑定到同一个 conversation_id，但各自使用自己的 avatar_id 和上下文。", "每轮回答前重新检索，确保新增行为记忆可以立即生效。", "若没有共同观点，A 随机抛出可公开话题；B 先判断兴趣，低于阈值就自然拒绝并结束。", "对话消息写入 PostgreSQL，之后尽力写入 Chroma。"], styles))
    story.append(P("阶段四：评判与成长", styles["h2"]))
    story.extend(bullets(["对话结束后，独立评判模型从性格匹配、兴趣激发、观点契合和沟通质量等维度评分。", "达到配置阈值时只调用推送接口占位，不直接发送真实消息。", "没有记忆命中时生成心灵感应题；用户选择后累计正向或反向证据。", "同一性格方向达到累计阈值后才调整画像，避免一次选择造成性格震荡。"], styles))

    story.append(P("3. 画像结构和数据职责", styles["h1"]))
    story.append(table([["画像部分", "回答什么问题", "主要来源"], ["profile_identity", "用户是谁？", "用户填写、知乎公开资料"], ["personality", "用户通常有什么稳定性格倾向？", "IPIP Big Five 测评和成长反馈"], ["style / style_examples", "应该怎样表达？", "知乎原文、测评结果、LLM 提炼"], ["expertise / interests", "用户擅长和关注什么？", "用户选择、知乎内容、LLM 提炼"], ["opinions", "用户对某主题怎么看？", "观点题、知乎内容、对话反馈"], ["behavior_memories", "遇到具体情境时可能怎么反应？", "社交情景题、行为记忆工具、对话反馈"], ["source_documents / memory_evidence", "依据是什么？", "知乎原始内容和引用片段"], ["memory_rules / policy", "检索和安全边界是什么？", "系统默认策略和用户配置"], ["growth_evaluations", "画像如何变化？", "对话评判和心灵感应题反馈"]], [36 * mm, 63 * mm, 77 * mm], styles))

    story.append(P("4. 检索和 Prompt 组装", styles["h1"]))
    story.append(P("固定画像不做向量检索，直接读取当前 active 版本：identity、personality、style、policy。它们回答“用户是谁”和“应该怎样表达”。", styles["body"]))
    story.append(P("经历、观点、行为、专长、兴趣、原始资料和聊天记录属于长内容，先做 PostgreSQL 关键词召回，同时用 Chroma 做语义召回；按 ID 合并后回 PostgreSQL 检查状态、权限、隐私和删除标记。", styles["body"]))
    story.append(code('''问题\n  ↓\n问题分析与改写\n  ↓\n并行：关键词检索 + Chroma 向量检索\n  ↓\n按 ID 合并、去重、排序、冲突处理、Token 截断\n  ↓\n固定画像 + 动态记忆 + 原始证据 + 当前聊天历史\n  ↓\n调用当前 Agent 的 LLM''', styles))
    story.append(rich("<b>重要边界：</b>retrieval/service.py 只提供显式调用的函数，不注册为 Agent Tool；Agent 不能自己发现数据库或 Chroma。行为记忆工具只负责提交提案，最终写入仍经过 ProfileRepository。", styles["note"]))

    story.append(P("5. LangGraph 对话原理", styles["h1"]))
    story.append(P("单 Agent 图的核心节点是 prepare_context、call_model、execute_tools 和 persist_answer。工具调用完成后回到 prepare_context，重新检索最新画像。双 Agent 编排器负责轮换 A/B，不把两人的画像混在一起。", styles["body"]))
    story.append(code('''话题门控：\nload_opinions\n  → find_shared_topics\n  → 共同观点存在？\n      是：select_shared_topic\n      否：select_random_topic\n  → ask_interest（B 判断兴趣）\n      感兴趣：进入正常对话\n      不感兴趣：persist_refusal → completed\n\n正常对话：\nA 开场 → B 回答 → B 提问 → A 回答 → ...\n最多 10 轮（最多 20 条 Agent 消息）''', styles))
    story.append(P("当前默认门控阈值：观点相似度 0.65、观点置信度 0.60、B 兴趣分数 0.55。阈值来自环境变量，前端不需要参与计算。", styles["body"]))

    story.append(P("6. PostgreSQL、Chroma 与聊天持久化", styles["h1"]))
    story.extend(bullets(["PostgreSQL 保存用户、画像版本、完整知乎原文、完整聊天内容、权限、状态、审计和评判结果。", "Chroma 集合 avatar_memories、source_documents、chat_messages 保存 embedding 和最小 payload。", "双写顺序是 PostgreSQL 提交成功后再写 Chroma；Chroma 失败不回滚聊天事实，交给 vector_sync_outbox 重试。", "一次 run_agent_dialogue() 对应一个 agent_chat_groups.chat_no；chat_messages 保存真实正文，查询聊天组时按 sequence_no 升序返回。", "A 和 B 共享 conversation_id，消息发送者由 chat_participants 和 participant_id 识别。"], styles))
    story.append(P("7. SQL 脚本执行顺序", styles["h1"]))
    story.append(P("当前仓库存在两套数据结构，执行前必须先确认使用哪一套。", styles["body"]))
    story.append(table([["数据结构", "特点", "适用代码"], ["schema.sql + migrations/002、003", "旧原型结构，用户和头像 ID 是 TEXT，database.initialize() 自动执行。", "app/main.py 的早期内存画像、性格和领域演示接口。"], ["postgresql_zhihu_schema.sql 等", "正式数字分身结构，用户、avatar、聊天和画像 ID 是 UUID，脚本需要手动按依赖执行。", "ProfileRepository、retrieval、ChatRepository、Agent 对话模块。"]], [42 * mm, 66 * mm, 68 * mm], styles))
    story.append(P("正式 PostgreSQL 数字分身结构的建议执行顺序：", styles["h2"]))
    story.append(code('''1. postgresql_zhihu_schema.sql\n2. postgresql_chat_schema.sql\n3. postgresql_profile_outbox.sql\n4. postgresql_agent_dialogue.sql\n5. postgresql_twin_initialization.sql\n6. postgresql_agent_chat_groups.sql''', styles))
    story.extend(bullets(["第1步创建 users、user_avatars、avatar_versions、avatar_memories、source_documents 等基础表。", "第2步创建 chat_conversations、chat_participants、chat_messages。", "第3步创建 PostgreSQL 到 Chroma 的 vector_sync_outbox。", "第4步创建 agent_dialogue_runs 和 agent_dialogue_evaluations。", "第5步创建初始化会话、心灵感应反馈和性格调整表。", "第6步创建面向用户查询的 agent_chat_groups 索引表。"], styles))
    story.append(rich("<b>不要混用：</b>postgresql_* 脚本依赖 UUID 版 users/user_avatars；schema.sql 是旧 TEXT 版结构。若要让 production runtime 全部使用正式表，应统一数据库连接、用户 ID 类型和迁移入口。", styles["note"]))

    story.append(P("8. 安全、权限和失败处理", styles["h1"]))
    story.extend(bullets(["知乎 token 只保存在服务端会话，日志和 API 响应不返回 API Key 或 access token。", "敏感、拒绝、过期、软删除或不属于当前 avatar 的记忆不能进入 Prompt。", "聊天详情必须满足当前用户是 initiator_user_id 或 invited_user_id；否则统一 404。", "模型失败时对话标记 failed；工具失败允许当前轮继续，但不能伪造“记忆已保存”。", "评判模型失败时保留聊天记录，禁止触发高质量推送。", "MAX_AGENT_DIALOGUES 默认10，单个双 Agent 对话最多10轮，并用 finally 释放信号量。"], styles))

    story.append(P("9. 前端落地建议", styles["h1"]))
    story.extend(bullets(["登录页：先 connect，再等待 callback，最后请求 /api/v1/me。", "初始化页：使用一个步骤状态机，页面刷新后通过 GET /v1/twin/initializations/{id} 恢复。", "领域页：先 GET /v1/domains，再 PUT /v1/domains/selections/me；保存 revision。", "性格页：先 GET questions，提交时保留 request_key，防止重复提交。", "聊天历史页：先请求 count 或列表，再点击 chat_no 请求 messages；不要直接拼接 conversation_id 查询。", "所有长文本展示都应支持加载态、授权过期、可重试错误和空状态。"], styles))

    story.append(P("10. 当前版本的已知边界", styles["h1"]))
    story.extend(bullets(["双 Agent 对话的核心 Python 编排和聊天组查询已存在，但当前没有完整的 HTTP 对话启动、后台任务和取消路由。", "初始化接口已能保存步骤并创建初始画像，但知乎资料到画像候选的完整 LLM 提炼闭环仍需继续接入。", "runtime 部分接口使用 X-User-Id，正式环境应统一切换为登录依赖，补充 session 到 user_id 的服务端映射。", "LangGraph PostgreSQL Checkpointer 已有适配器文件，但图编译和生命周期仍应在生产启动流程中统一接入。", "数据库脚本和旧 migration 并行存在，后续应选择一个正式迁移入口，避免两套 ID 类型长期并存。"], styles))
    NumberedDocTemplate(str(path), "TwinLoop 数字分身项目说明").build(story)


def main() -> None:
    """生成两份项目 PDF。"""
    register_fonts()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    build_api_pdf(OUTPUT / "TwinLoop-后端接口文档.pdf")
    build_project_pdf(OUTPUT / "TwinLoop-项目说明.pdf")
    print(f"已生成：{OUTPUT / 'TwinLoop-后端接口文档.pdf'}")
    print(f"已生成：{OUTPUT / 'TwinLoop-项目说明.pdf'}")


if __name__ == "__main__":
    main()
