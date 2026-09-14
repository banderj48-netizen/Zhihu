"""Read-only code audit with synthetic data in a disposable PostgreSQL schema."""
import ast
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, Mock, AsyncMock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
from db.database import database_url, connect
os.environ['TWINLOOP_TEST_DATABASE_URL'] = database_url()
from test_retrieval_integration import RetrievalWriteTests
from agent.runtime.initialization import InitializationService
from agent.runtime.mind_reading import MindReadingService
from agent.profile.card_renderer import render_chara_card
from agent.profile.outbox import sync_pending
from agent.profile.chat_repository import ChatRepository
from agent.personality.assessment import ITEMS, score_assessment
from agent.runtime.matching import AvatarMatcher
from agent.runtime.model_builder import _post_chat_completion
from fastapi import FastAPI, APIRouter, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from typing import Any

results = {}
def capture(name, fn):
    try:
        results[name] = fn()
    except Exception as exc:
        results[name] = {'exception': type(exc).__name__, 'constraint': getattr(getattr(exc, 'diag', None), 'constraint_name', None)}

test = RetrievalWriteTests()
test.setUp()
try:
    with connect() as db:
        for name in ('postgresql_agent_dialogue.sql', 'postgresql_twin_initialization.sql'):
            text = (ROOT / 'backend/db' / name).read_text(encoding='utf-8-sig')
            import re
            text = re.sub(r'(?m)^(BEGIN;|COMMIT;|CREATE EXTENSION IF NOT EXISTS pgcrypto;)\s*$', '', text)
            db.execute(text.replace('public.', test.schema + '.'))
    service = InitializationService()
    capture('init_login_style_user_id', lambda: service.create('user_0123456789abcdef'))
    capture('init_uuid_without_users_record', lambda: service.create(str(uuid4())))
    with connect() as db:
        u = str(db.execute('INSERT INTO users DEFAULT VALUES RETURNING id').fetchone()['id'])
    sid = str(service.create(u)['id'])
    raw_answers = {item.id: 1 if item.reverse else 5 for item in ITEMS}
    service.save_step(sid, 'personality', {'answers': raw_answers})
    service.save_step(sid, 'domains', {'interests': [{'domain_id': 'computer.03'}]})
    service.save_step(sid, 'opinion-answers', {'answers': [{'selected_option_id': 'opt_b', 'custom_text': 'synthetic opinion'}]})
    service.save_step(sid, 'social-answers', {'answers': [{'selected_option_id': 'opt_b', 'elapsed_seconds': 15}]})
    init = asyncio.run(service.complete(sid, {'display_name': 'Audit twin', 'occupation': 'engineer'}))
    with connect() as db:
        results['init_with_all_raw_steps'] = {
            'status': service.get(sid)['status'],
            'scores': db.execute('SELECT scores FROM avatar_personality WHERE avatar_version_id=%s', (init['version_id'],)).fetchone()['scores'],
            **{table: db.execute('SELECT count(*) AS n FROM ' + table + ' WHERE avatar_id=%s', (init['avatar_id'],)).fetchone()['n'] for table in ('avatar_memories', 'source_documents', 'avatar_style_examples', 'vector_sync_outbox')}
        }
    with connect() as db:
        u2 = str(db.execute('INSERT INTO users DEFAULT VALUES RETURNING id').fetchone()['id'])
    sid2 = str(service.create(u2)['id'])
    service.save_step(sid2, 'personality', score_assessment(raw_answers, 'audit_assessment'))
    capture('init_with_completed_score_result', lambda: asyncio.run(service.complete(sid2, {'display_name': 'Audit scored twin'})))
    doc = test.writer.write_source(user_id=test.user, avatar_id=test.avatar, platform='audit', document_type='answer', content='synthetic source')
    saved = test.writer.apply_memory_proposal(test.proposal(source_refs=[doc]))
    with connect() as db:
        row = db.execute('SELECT snapshot FROM avatar_versions WHERE id=%s', (saved['version_id'],)).fetchone()
        results['memory_proposal'] = {'snapshot_memories': row['snapshot'].get('memories'), 'linked_evidence': db.execute('SELECT count(*) AS n FROM memory_evidence WHERE memory_id=%s', (saved['memory_id'],)).fetchone()['n']}
    capture('standard_json_card', lambda: len(json.dumps(render_chara_card(test.user), ensure_ascii=False)))
    mind = MindReadingService()
    q = mind.create_question(test.user, test.avatar, None, {'options': [{'id': 'a', 'text': 'A'}, {'id': 'b', 'text': 'B'}], 'agent_option_id': 'a'})
    results['invalid_mind_option'] = mind.answer(str(q['id']), 'does_not_exist')
    results['repeat_mind_answer'] = mind.answer(str(q['id']), 'a')
    with connect() as db:
        results['growth_after_feedback'] = {table: db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] for table in ('avatar_personality_adjustments', 'avatar_growth_evaluations')}
    chat = ChatRepository()
    cid = chat.create_conversation()
    with connect() as db:
        pid = str(db.execute('INSERT INTO chat_participants(conversation_id,avatar_id) VALUES(%s,%s) RETURNING id', (cid, test.avatar)).fetchone()['id'])
    msg = chat.append_message(cid, pid, 'original synthetic message', client_message_id='one')
    chat.append_message(cid, pid, 'replaced synthetic message', client_message_id='one')
    with connect() as db:
        results['retry_changed_chat_content'] = db.execute('SELECT content FROM chat_messages WHERE id=%s', (msg['message_id'],)).fetchone()['content']
    class FailureVector:
        async def upsert(self, *a, **kw):
            raise RuntimeError('synthetic vector outage')
    results['outbox_failure'] = asyncio.run(sync_pending(FailureVector()))
    results['outbox_next_run'] = asyncio.run(sync_pending(test.vector))
    with connect() as db:
        db.execute("UPDATE vector_sync_outbox SET status='pending'")
        db.execute("UPDATE avatar_memories SET status='rejected' WHERE id=%s", (saved['memory_id'],))
    results['outbox_rejected'] = asyncio.run(sync_pending(test.vector))
    results['rejected_indexed'] = saved['memory_id'] in test.vector.collections.get('avatar_memories', {})
finally:
    test.doCleanups()

# Load only the actual route definitions; unavailable LangGraph imports are not stubbed
# into the application. Services are doubles here to observe FastAPI dispatch order.
source = ast.parse((ROOT / 'backend/agent/runtime/api.py').read_text(encoding='utf-8-sig'))
names = {'InitStep', 'InitComplete', 'save_initialization_step', 'complete_initialization'}
nodes = [n for n in source.body if getattr(n, 'name', None) in names]
ns = dict(APIRouter=APIRouter, Header=Header, HTTPException=HTTPException, BaseModel=BaseModel, Field=Field, Any=Any)
ns['router'] = APIRouter(prefix='/v1/twin')
ns['_initializations'] = Mock(save_step=Mock(return_value={'route': 'save_step'}), complete=AsyncMock(return_value={'route': 'complete'}))
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<actual_api_routes>', 'exec'), ns)
app = FastAPI()
app.include_router(ns['router'])
response = TestClient(app).post('/v1/twin/initializations/audit/complete', json={'identity': {'display_name': 'Audit'}})
results['complete_route_dispatch'] = {'response': response.json(), 'complete_called': ns['_initializations'].complete.call_count, 'save_step_args': ns['_initializations'].save_step.call_args.args}
capture('matching_sync_presence_provider', lambda: asyncio.run(AvatarMatcher(lambda scene: [{'avatar_id': 'b', 'status': 'idle'}]).match('a', 'cafe', 'random')))
class ToolOnlyResponse:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps({'choices': [{'message': {'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'save_behavior_memory', 'arguments': '{}'}}]}}]}).encode()
with patch('agent.runtime.model_builder.urlopen', return_value=ToolOnlyResponse()):
    capture('tool_only_llm_response', lambda: _post_chat_completion('audit', 'synthetic', {}, api_key='synthetic', base_url='https://example.invalid/v1'))

out = ROOT / 'backend/reports/audit-probe-results.json'
out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
