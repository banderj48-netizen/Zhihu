from fastapi import FastAPI, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4
from datetime import datetime, timezone
from threading import Lock
from enum import Enum
app=FastAPI(title='TwinLoop API',version='0.1.0')
lock=Lock(); tasks={}; profiles={}; versions={}
def now(): return datetime.now(timezone.utc).isoformat()
def uid(x): return x or 'local-demo-user'
class Provider(str,Enum): zhihu='zhihu'
class Consent(BaseModel): provider:Provider; scopes:list[str]=Field(min_length=1); granted:bool=True
class ImportJob(BaseModel): consent_id:str; source:Provider=Provider.zhihu; options:dict={}
class Patch(BaseModel): data:dict={}
class Publish(BaseModel): expected_revision:int=0
def run(tid,user):
 for status,progress,msg in [('fetching',15,'正在读取已授权数据'),('storing_raw',30,'保存原始数据'),('extracting',60,'抽取事实、领域、观点与风格'),('review',85,'等待用户确认画像'),('completed',100,'画像草稿已生成')]:
  with lock: tasks[tid].update(status=status,progress=progress,message=msg,updated_at=now())
  if status=='completed': profiles[user]={'revision':0,'status':'draft','data':{'facts':[],'domains':[],'stances':[],'style':{},'memories':[]},'evidence':[]}
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
def create_job(body:ImportJob,bg:BackgroundTasks,x_user_id:str|None=Header(default=None)):
 t={'id':'job_'+uuid4().hex,'user_id':uid(x_user_id),'source':body.source,'status':'queued','progress':0,'message':'任务已排队','created_at':now(),'updated_at':now()}; tasks[t['id']]=t; bg.add_task(run,t['id'],t['user_id']); return t
@app.get('/v1/import-jobs/{tid}')
def get_job(tid:str,x_user_id:str|None=Header(default=None)):
 t=tasks.get(tid)
 if not t or t['user_id']!=uid(x_user_id): raise HTTPException(404,'任务不存在')
 return t
@app.get('/v1/twin/profile')
def profile(x_user_id:str|None=Header(default=None)):
 p=profiles.get(uid(x_user_id))
 if not p: raise HTTPException(404,'尚未生成画像')
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
def build_card(profile,user,vid):
 d=profile['data']; entries=[]
 for i,m in enumerate(d.get('memories',[]),1):
  if m.get('share'): entries.append({'id':i,'keys':m.get('keys',[]),'content':m.get('content',''),'enabled':True,'insertion_order':i,'constant':m.get('depth')=='deep','selective':False,'position':'after_char','extensions':{'twin':{'memory_id':m.get('id',f'memory_{i}'),'depth':m.get('depth','shallow'),'source_refs':m.get('source_refs',[]),'confirmation_status':'confirmed','version':m.get('version',1)}}})
 return {'spec':'chara_card_v2','spec_version':'2.0','data':{'name':d.get('name',f'Twin_{user[:8]}'),'description':'；'.join(map(str,d.get('facts',[])[:8])) or '主人尚未提供公开身份事实。','personality':d.get('personality','总体人格尚未完成正式测评，具体反应以条件记忆为准。'),'scenario':'数字分身在虚拟社交场景中交流。虚拟经历不等于主人的现实经历。','first_mes':'你好。','mes_example':d.get('mes_example',''),'creator_notes':f'TwinLoop version {vid}; 由用户确认的资料生成。','system_prompt':'{{original}}\n不编造主人的经历、能力或现实承诺；未知时自然说明。','post_history_instructions':'{{original}}\n按适用条件和例外回应。','alternate_greetings':[],'tags':['TwinLoop'],'creator':'TwinLoop','character_version':vid,'character_book':{'name':'三层世界书','description':'深层原则、中层条件反应、浅层事件。','recursive_scanning':False,'entries':entries},'extensions':{'twin':{'schema_version':'2.1-proposal','owner_id':user,'version_id':vid,'assessment':d.get('assessment',{'status':'not_completed'}),'domain_profile':d.get('domains',[]),'private_answers_included':False}}}}
