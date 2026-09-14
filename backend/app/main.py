"""TwinLoop FastAPI 应用入口。

本文件只负责组装 FastAPI 应用、注册路由和配置中间件；数据库连接、模型实例
以及业务服务仍由各自模块负责。生产环境建议使用 ``uvicorn app.main:app``
启动，避免在路由模块中重复创建应用实例。
"""

# 必须在导入任何读取环境变量的模块之前加载 .env
from app.config import load_env as _load_env
_ENV_LOADED=_load_env()

from fastapi import FastAPI, BackgroundTasks, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from uuid import uuid4
from datetime import datetime, timezone
from threading import Lock
from enum import Enum
from agent.personality import export_personality, public_questions, render_personality, score_assessment
from agent.personality.repository import latest_assessment, save_assessment, save_skipped
from agent.domains.api import router as domains_router
from agent.domains.repository import get_selections
from app.auth import service as auth_service
from app.auth import session as auth_session
from app.auth.router import router as auth_router
from app.auth.schemas import fail as auth_fail, new_request_id
from app.consent import service as consent_service
from app.consent.router import router as consent_router
from app.consent import zhihu_oauth as _zhihu_oauth
from app.imports.router import router as imports_router
from agent.runtime.api import router as twin_runtime_router
from app.imports import zhihu_client as _zhihu_client
app=FastAPI(title='TwinLoop API',version='0.1.0')
app.include_router(domains_router)

# 前端与后端分端口时需要放行凭证跨域，否则浏览器不会带上 HttpOnly Cookie。
# allow_credentials=True 时不能使用通配来源，必须逐个列出。
import os as _os
_origins=[o.strip() for o in _os.environ.get('TWINLOOP_CORS_ORIGINS','http://127.0.0.1,http://localhost,http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000').split(',') if o.strip()]
app.add_middleware(CORSMiddleware,allow_origins=_origins,allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

@app.exception_handler(auth_service.AuthError)
async def _auth_error_handler(request:Request,exc:auth_service.AuthError):
 rid=request.headers.get('X-Request-Id') or new_request_id()
 return JSONResponse(status_code=exc.status_code,content=auth_fail(exc.code,exc.message,rid))

@app.exception_handler(consent_service.ConsentError)
async def _consent_error_handler(request:Request,exc:consent_service.ConsentError):
 rid=request.headers.get('X-Request-Id') or new_request_id()
 return JSONResponse(status_code=exc.status_code,content=auth_fail(exc.code,exc.message,rid))

app.include_router(auth_router)
app.include_router(consent_router)
app.include_router(imports_router)
app.include_router(twin_runtime_router)

# 本地浏览器入口统一导向 Next.js 前端。
from fastapi.responses import RedirectResponse
@app.get('/',include_in_schema=False)
def _login_test_page():
 # 本地前后端分端口运行时，访问 API 根路径也回到前端，避免 OAuth
 # 成功后因旧回调/书签停留在 8000 的后端测试页。
 return RedirectResponse('http://127.0.0.1:3000/', status_code=307)

@app.on_event('startup')
def _report_oauth_config():
 print('[config] .env', '已加载' if _ENV_LOADED else '未找到（使用系统环境变量）')
 print('[consent] 知乎 OAuth 配置:', '完整' if _zhihu_oauth.is_configured() else '!! 不完整，请设置 ZHIHU_OAUTH_APP_ID / APP_KEY / REDIRECT_URI')
 if _zhihu_oauth.REDIRECT_URI: print('[consent] redirect_uri =',_zhihu_oauth.REDIRECT_URI)
 print('[imports] Access Secret:', '已配置' if _zhihu_client.is_configured() else '!! 未配置 ZHIHU_ACCESS_SECRET，无法读取用户数据')
lock=Lock(); tasks={}; profiles={}; versions={}
def now(): return datetime.now(timezone.utc).isoformat()
def uid(x): return x or 'local-demo-user'
class Provider(str,Enum): zhihu='zhihu'
class Consent(BaseModel): provider:Provider; scopes:list[str]=Field(min_length=1); granted:bool=True
class ImportJob(BaseModel): consent_id:str; source:Provider=Provider.zhihu; options:dict={}
class Patch(BaseModel): data:dict={}
class Publish(BaseModel): expected_revision:int=0
class PersonalityAssessment(BaseModel):
 answers:dict[str,int]=Field(default_factory=dict)
 notes:str|None=None
 request_key:str|None=None
class PersonalitySkip(BaseModel): request_key:str|None=None
def run(tid,user,oauth_token=None):
 try:
  with lock: tasks[tid].update(status='fetching',progress=15,message='正在读取已授权数据',updated_at=now())
  if not oauth_token: raise RuntimeError('知乎会话 token 不存在或已过期')
  results = {
   'contents': _zhihu_client.fetch_contents(oauth_token),
   'followees': _zhihu_client.fetch_followees(oauth_token),
   'favlists': _zhihu_client.fetch_favlists(oauth_token),
   'collections': _zhihu_client.fetch_collections(oauth_token),
  }
  print('[import-job] zhihu raw response:', json.dumps(results, ensure_ascii=False, default=str), flush=True)
  with lock: tasks[tid].update(status='completed',progress=100,message='知乎数据读取完成',result=results,updated_at=now())
 except Exception as exc:
  print('[import-job] zhihu fetch error:', repr(exc), flush=True)
  with lock: tasks[tid].update(status='failed',progress=100,message=str(exc),updated_at=now())
@app.get('/health')
def health(): return {'ok':True,'service':'twinloop-api','time':now()}
@app.get('/v1/me')
def me(x_user_id:str|None=Header(default=None)): 
 p=profiles.get(uid(x_user_id)); return {'user_id':uid(x_user_id),'twin':{'status':p['status'] if p else 'not_started','revision':p['revision'] if p else None}}
@app.post('/v1/consents')
def consent(body:Consent,x_user_id:str|None=Header(default=None)):
 if not body.granted: raise HTTPException(400,'未获得数据授权')
 return {'id':'consent_'+uuid4().hex,'user_id':uid(x_user_id),'provider':body.provider,'scopes':body.scopes,'status':'active','created_at':now()}
@app.post('/v1/import-jobs',status_code=202)
def create_job(request:Request,body:ImportJob,bg:BackgroundTasks,x_user_id:str|None=Header(default=None)):
 user=uid(x_user_id); token=auth_session.get_zhihu_token(auth_session.read_session_id(request))
 t={'id':'job_'+uuid4().hex,'user_id':user,'source':body.source,'status':'queued','progress':0,'message':'任务已排队','created_at':now(),'updated_at':now()}; tasks[t['id']]=t; bg.add_task(run,t['id'],user,token); return t
@app.get('/v1/import-jobs/{tid}')
def get_job(tid:str,x_user_id:str|None=Header(default=None)):
 t=tasks.get(tid)
 if not t or t['user_id']!=uid(x_user_id): raise HTTPException(404,'任务不存在')
 return t
@app.get('/v1/twin/profile')
def profile(x_user_id:str|None=Header(default=None)):
 p=profiles.get(uid(x_user_id))
 if not p: raise HTTPException(404,'尚未生成画像')
 assessment=latest_assessment(uid(x_user_id))
 if assessment: p['data']['personality']=assessment
 return p
@app.patch('/v1/twin/profile')
def patch(body:Patch,x_user_id:str|None=Header(default=None)):
 p=profiles.get(uid(x_user_id))
 if not p: raise HTTPException(404,'尚未生成画像')
 with lock: p['data'].update(body.data);p['revision']+=1;p['updated_at']=now()
 return p
@app.post('/v1/twin/versions',status_code=201)
def publish(body:Publish,x_user_id:str|None=Header(default=None)):
 user=uid(x_user_id);p=profiles.get(user)
 if not p: raise HTTPException(404,'尚未生成画像')
 if body.expected_revision!=p['revision']: raise HTTPException(409,'画像已被更新，请重新读取后发布')
 vid='version_'+uuid4().hex; card=build_card(p,user,vid); v={'id':vid,'user_id':user,'revision':p['revision'],'created_at':now(),'card':card}; versions[vid]=v;p['status']='published';return v
@app.get('/v1/twin/versions/{vid}')
def version(vid:str,x_user_id:str|None=Header(default=None)):
 v=versions.get(vid)
 if not v or v['user_id']!=uid(x_user_id): raise HTTPException(404,'版本不存在')
 return v
@app.get('/v1/personality/questions')
def personality_questions():
 return public_questions()
@app.post('/v1/personality/assessments')
def personality_assessment(body:PersonalityAssessment,x_user_id:str|None=Header(default=None)):
 user=uid(x_user_id)
 assessment_id='assessment_'+uuid4().hex
 try:
  result=score_assessment(body.answers,assessment_id,body.notes)
 except ValueError as exc:
  raise HTTPException(422,str(exc)) from exc
 result=save_assessment(user,result,body.request_key)
 p=profiles.get(user)
 if not p:
  p={'revision':0,'status':'draft','data':{'facts':[],'domains':[],'stances':[],'style':{},'memories':[],'personality':result},'evidence':[],'updated_at':now()}
  profiles[user]=p
 else:
  with lock:
   p['data']['personality']=result
   p['revision']+=1
   p['updated_at']=now()
 return result
@app.post('/v1/personality/skip')
def personality_skip(body:PersonalitySkip,x_user_id:str|None=Header(default=None)):
 user=uid(x_user_id)
 result=save_skipped(user,'assessment_'+uuid4().hex,body.request_key)
 p=profiles.get(user)
 if not p:
  p={'revision':0,'status':'draft','data':{'facts':[],'domains':[],'stances':[],'style':{},'memories':[],'personality':result},'evidence':[],'updated_at':now()}
  profiles[user]=p
 else:
  with lock:
   p['data']['personality']=result
   p['revision']+=1
   p['updated_at']=now()
 return result
@app.get('/v1/personality/assessments/latest')
def personality_latest(x_user_id:str|None=Header(default=None)):
 result=latest_assessment(uid(x_user_id))
 if not result: raise HTTPException(404,'尚未完成性格测评')
 return result
def build_card(profile,user,vid):
 d=profile['data']; entries=[]
 try:
  domain_profile=get_selections(user)
  if not domain_profile.get('interests') and not domain_profile.get('expertise') and d.get('domains'):
   domain_profile=d.get('domains')
 except Exception:
  domain_profile=d.get('domains',[])
 personality=d.get('personality') or latest_assessment(user)
 for i,m in enumerate(d.get('memories',[]),1):
  if m.get('share'): entries.append({'id':i,'keys':m.get('keys',[]),'content':m.get('content',''),'enabled':True,'insertion_order':i,'constant':m.get('depth')=='deep','selective':False,'position':'after_char','extensions':{'twin':{'memory_id':m.get('id',f'memory_{i}'),'depth':m.get('depth','shallow'),'source_refs':m.get('source_refs',[]),'confirmation_status':'confirmed','version':m.get('version',1)}}})
 return {'spec':'chara_card_v2','spec_version':'2.0','data':{'name':d.get('name',f'Twin_{user[:8]}'),'description':'；'.join(map(str,d.get('facts',[])[:8])) or '主人尚未提供公开身份事实。','personality':render_personality(personality),'scenario':'数字分身在虚拟社交场景中交流。虚拟经历不等于主人的现实经历。','first_mes':'你好。','mes_example':d.get('mes_example',''),'creator_notes':f'TwinLoop version {vid}; 由用户确认的资料生成。','system_prompt':'{{original}}\n不编造主人的经历、能力或现实承诺；未知时自然说明。','post_history_instructions':'{{original}}\n按适用条件和例外回应。','alternate_greetings':[],'tags':['TwinLoop'],'creator':'TwinLoop','character_version':vid,'character_book':{'name':'三层世界书','description':'深层原则、中层条件反应、浅层事件。','recursive_scanning':False,'entries':entries},'extensions':{'twin':{'schema_version':'2.1-proposal','owner_id':user,'version_id':vid,'assessment':{'status':personality.get('status') if isinstance(personality,dict) else 'not_completed'},'personality':export_personality(personality if isinstance(personality,dict) else None),'domain_profile':domain_profile,'private_answers_included':False}}}}


def run_server() -> None:
 """使用 Uvicorn 在本机启动 FastAPI 服务。

 直接执行 ``python -m app.main`` 时会进入此函数；部署环境仍推荐使用
 ``backend/run_server.ps1``，因为脚本会自动设置项目根目录和 ``PYTHONPATH``。
 """
 import uvicorn

 # 传入已创建的 app 对象，避免 Uvicorn 再次按字符串导入时丢失项目路径。
 uvicorn.run(app, host=_os.environ.get('BACKEND_HOST', '127.0.0.1'), port=int(_os.environ.get('BACKEND_PORT', '8000')))


if __name__ == '__main__':
 run_server()
