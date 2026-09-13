from __future__ import annotations
from datetime import date, datetime
import json
from db.database import connect

def _json(value):
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, dict): return {k:_json(v) for k,v in value.items()}
    if isinstance(value, list): return [_json(v) for v in value]
    return value

def render_chara_card(user_id: str) -> dict:
    """Render a chara_card_v2 strictly from the active collaborator schema."""
    with connect() as db:
        p=db.execute("""SELECT a.id AS avatar_id,v.id AS version_id,v.version_no,i.display_name,i.summary,i.occupation,i.location,i.age,p.model_name,p.scores,p.style_tags,p.confidence,p.status AS personality_status,s.tone,s.structure_rules,s.verbosity,s.technical_density,s.sentence_style,s.uncertainty_style,s.preferred_registers,s.avoid_rules,pol.* FROM user_avatars a JOIN avatar_versions v ON v.id=a.current_version_id AND v.status='active' LEFT JOIN avatar_identity i ON i.avatar_version_id=v.id LEFT JOIN avatar_personality p ON p.avatar_version_id=v.id LEFT JOIN avatar_styles s ON s.avatar_version_id=v.id LEFT JOIN avatar_policies pol ON pol.avatar_id=a.id WHERE a.user_id=%s AND a.status<>'archived'""",(user_id,)).fetchone()
        if not p: raise LookupError("active avatar not found")
        memories=db.execute("SELECT id,memory_type,topic,content,structured_data,level,confidence,status,privacy FROM avatar_memories WHERE avatar_id=%s AND status IN ('confirmed','unconfirmed') AND privacy IN ('public','private') ORDER BY CASE level WHEN 'deep' THEN 1 WHEN 'middle' THEN 2 ELSE 3 END,updated_at DESC",(p['avatar_id'],)).fetchall()
    entries=[]
    for n,m in enumerate(memories,1):
        entries.append({'id':n,'keys':[x for x in [m['topic'],m['memory_type']] if x],'content':m['content'],'enabled':True,'insertion_order':n,'constant':m['level']=='deep','selective':m['level']!='deep','position':'after_char','extensions':{'twin':{'memory_id':str(m['id']),'memory_type':m['memory_type'],'level':m['level'],'confidence':m['confidence'],'status':m['status'],'privacy':m['privacy'],'structured_data':_json(m['structured_data'])}}})
    return {'spec':'chara_card_v2','spec_version':'2.0','data':{'name':p['display_name'] or 'Twin','description':p['summary'] or p['occupation'] or '','personality':json.dumps({'model':p['model_name'],'scores':_json(p['scores'] or {}),'style_tags':_json(p['style_tags'] or [])},ensure_ascii=False),'scenario':'数字分身在虚拟社交场景中交流。','first_mes':'你好。','mes_example':'','creator_notes':f"TwinLoop version {p['version_id']}",'system_prompt':'{{original}}','post_history_instructions':'{{original}}','alternate_greetings':[],'tags':['TwinLoop'],'creator':'TwinLoop','character_version':str(p['version_id']),'character_book':{'name':'三层世界书','description':'深层原则、中层条件反应、浅层事件。','recursive_scanning':False,'entries':entries},'extensions':{'twin':{'schema_version':'digital_twin_v1','owner_id':str(user_id),'avatar_id':str(p['avatar_id']),'version_id':str(p['version_id']),'personality':{'model':p['model_name'],'scores':_json(p['scores'] or {}),'style_tags':_json(p['style_tags'] or []),'confidence':p['confidence'],'status':p['personality_status']},'policy':{k:v for k,v in p.items() if k.startswith('can_') or k.startswith('must_') or k in ('sensitive_attributes_policy','external_action_requires_confirmation')}}}}}
