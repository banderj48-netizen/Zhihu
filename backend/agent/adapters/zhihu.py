"""Official Zhihu CLI adapter for public domain research snippets."""
from __future__ import annotations
import json, os, subprocess
from dataclasses import dataclass, asdict
from agent.domains.catalog import DomainNode
CLI = os.getenv("ZHIHU_CLI", r"C:\Users\bcZho\AppData\Local\ZhihuCLI\current\zhihu-cli.exe")
@dataclass(frozen=True)
class ZhihuEvidence:
    title:str; url:str; content_type:str; snippet:str; author:str|None; edit_time:int|None; vote_count:int|None; comment_count:int|None
def _run(*args:str, timeout:int=30)->dict:
    try: p=subprocess.run([CLI,*args],capture_output=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired) as e: raise RuntimeError('知乎 CLI 不可用或请求超时') from e
    if p.returncode: raise RuntimeError('知乎公开数据请求失败')
    raw = p.stdout.decode('utf-8', errors='replace')
    if '�' in raw:
        raw = p.stdout.decode('gb18030', errors='replace')
    try: x=json.loads(raw)
    except json.JSONDecodeError as e: raise RuntimeError('知乎 CLI 返回格式无效') from e
    if x.get('Code') not in (0,None): raise RuntimeError('知乎请求被拒绝或达到配额限制')
    return x.get('Data',x)
def search_domain(node:DomainNode,count:int=8)->list[dict]:
    if not 1<=count<=10: raise ValueError('count must be 1..10')
    data=_run('search','zhihu','--query',f'{node.label} 争议 取舍 前沿 实践','--count',str(count))
    return [asdict(ZhihuEvidence(str(i.get('Title','')),str(i.get('Url','')),str(i.get('ContentType','')),str(i.get('ContentText','')),i.get('AuthorName'),i.get('EditTime'),i.get('VoteUpCount'),i.get('CommentCount'))) for i in data.get('Items',[])]
