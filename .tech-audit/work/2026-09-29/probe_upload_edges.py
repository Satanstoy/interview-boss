"""Offline audit probes: execute actual AST-extracted functions on in-memory DBs.
No application startup, production database, network or LLM calls.
Assertions confirm defects in the audited baseline, not desired behavior.
"""
import ast
import asyncio
import json
import logging
from pathlib import Path
import sqlite3
import sys
import types
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

def load(path, names, ns):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    for n in nodes:
        n.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), ns)

def database():
    c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
    c.executescript('''
    CREATE TABLE users(id INTEGER PRIMARY KEY);
    INSERT INTO users VALUES(1),(2);
    CREATE TABLE interview(id INTEGER PRIMARY KEY, url TEXT, company TEXT, round TEXT, focus TEXT, questions_list TEXT, difficulty TEXT, season TEXT, owner_id INTEGER, status TEXT, url_signature TEXT, job_position TEXT, deleted_at TEXT);
    CREATE TABLE jd(id INTEGER PRIMARY KEY);
    CREATE TABLE questions_detail(id INTEGER PRIMARY KEY, interview_id INTEGER, url TEXT, company TEXT, round TEXT, question TEXT, cat1 TEXT, cat2 TEXT, tags TEXT, difficulty TEXT, diff_tag TEXT, job_position TEXT, owner_id INTEGER, status TEXT, deleted_at TEXT);
    CREATE TABLE analysis_queue(id INTEGER PRIMARY KEY, interview_id INTEGER, question_detail_id INTEGER, status TEXT, owner_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    ns={'logger':logging.getLogger('probe')}
    load('backend/app/db/migrations/public_contributions.py', ['_migration_102_public_contribution_workflow'], ns)
    ns['_migration_102_public_contribution_workflow'](c)
    c.execute("INSERT INTO interview(id,url,company,owner_id,status) VALUES(1,'https://example.test/private','PRIVATE_COMPANY',1,'approved')")
    c.execute("INSERT INTO questions_detail(id,interview_id,question) VALUES(1,1,'Original question')")
    c.commit(); return c

ns={'json':json,'Any':Any,'REQUEST_ACTIVE_STATUSES':('pending_review','changes_requested','approved_for_processing','queued','processing','failed')}
tree=ast.parse((ROOT/'backend/app/services/public_contributions.py').read_text())
load('backend/app/services/public_contributions.py',[n.name for n in tree.body if isinstance(n,ast.FunctionDef)],ns)
utils=types.ModuleType('app.db.utils'); utils._extract_url_signature=lambda url: url
sys.modules['app.db.utils']=utils
qns={'List':list,'Dict':dict,'get_db_connection':lambda: (_ for _ in ()).throw(AssertionError('unexpected DB'))}
load('backend/app/services/pipeline/queue.py',['enqueue_questions'],qns)
queue=types.ModuleType('app.services.pipeline.queue');queue.enqueue_questions=qns['enqueue_questions']
sys.modules['app.services.pipeline.queue']=queue

c=database();r=ns['create_public_contribution_request'](c,'interview',1,1)
r=ns['approve_public_contribution'](c,r['id'],2,review_fields={'company':'REDACTED'})
company=c.execute('SELECT company FROM interview WHERE id=?',(r['public_interview_id'],)).fetchone()[0]
assert company=='PRIVATE_COMPANY'
print('CONFIRMED review_fields company=REDACTED recorded but public projection retains PRIVATE_COMPANY')

qid=c.execute('SELECT id FROM analysis_queue').fetchone()[0]
c.execute("UPDATE analysis_queue SET status='failed' WHERE id=?",(qid,));c.commit()
ns['mark_public_contribution_queue_failed'](c,[qid],'synthetic failure')
r=ns['approve_public_contribution'](c,r['id'],2)
assert r['status']=='published' and c.execute('SELECT status FROM analysis_queue WHERE id=?',(qid,)).fetchone()[0]=='failed'
print('CONFIRMED failed contribution reapproval reports published while its only queue row stays failed')

# A second snapshot with a new question on the same URL adds detail but not list text.
c.execute("INSERT INTO questions_detail(id,interview_id,question) VALUES(3,1,'New question')");c.commit()
r2=ns['create_public_contribution_request'](c,'interview',1,1)
r2=ns['approve_public_contribution'](c,r2['id'],2)
public=c.execute('SELECT questions_list FROM interview WHERE id=?',(r2['public_interview_id'],)).fetchone()[0]
assert 'New question' not in public
assert c.execute('SELECT count(*) FROM questions_detail WHERE interview_id=?',(r2['public_interview_id'],)).fetchone()[0]==2
print('CONFIRMED same-URL later contribution adds public detail but leaves interview question list stale')

# Retry guard only checks immediate children, not the root retry family.
c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
c.executescript('''CREATE TABLE jobs(id INTEGER PRIMARY KEY,job_type TEXT,status TEXT,created_by INTEGER,progress_total INTEGER,available_at TEXT,parent_job_id INTEGER,idempotency_key TEXT);CREATE TABLE job_payloads(job_id INTEGER PRIMARY KEY,payload TEXT);
INSERT INTO jobs VALUES(1,'submit_import','failed',1,6,NULL,NULL,NULL),(2,'submit_import','failed',1,6,NULL,1,NULL),(3,'submit_import','running',1,6,NULL,2,NULL);
INSERT INTO job_payloads VALUES(1,'{}');''');c.commit()
t=ast.parse((ROOT/'backend/app/routers/submit.py').read_text());outer=next(n for n in t.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='retry_submit_job');inner=next(n for n in outer.body if isinstance(n,ast.FunctionDef))
retry_ns={'get_db_connection':lambda:c,'user':{'id':1},'job_id':1,'json':json,'HTTPException':RuntimeError}
exec(compile(ast.Module(body=[inner],type_ignores=[]),'backend/app/routers/submit.py','exec'),retry_ns)
result=retry_ns['_create_retry']();assert result['created'] and result['job_id']==4
assert c.execute("SELECT count(*) FROM jobs WHERE status IN ('pending','running')").fetchone()[0]==2
print('CONFIRMED retry of root creates new pending attempt despite existing running grandchild')

# Route-level SSE owner predicate grants admin access to private result contents.
c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
c.execute('CREATE TABLE jobs(id,status,progress_current,progress_total,progress_message,progress_phase,result,last_error,created_by)')
c.execute('INSERT INTO jobs VALUES(1,\'completed\',6,6,\'\',\'save\',?,NULL,1)',(json.dumps({'target':'personal','saved_data':{'private_marker':'PRIVATE_RESULT'}}),));c.commit()
async def run_db(fn):return fn()
class Stream:
    def __init__(self,iterator,**kwargs):self.body_iterator=iterator
route_ns={'Depends':lambda x:None,'get_current_user':None,'get_db_connection':lambda:c,'run_db':run_db,'json':json,'asyncio':asyncio,'StreamingResponse':Stream}
load('backend/app/routers/bank_build.py',['stream_job_progress'],route_ns)
async def check():
    resp=await route_ns['stream_job_progress'](1,{'id':2,'is_admin':1}); events=[x async for x in resp.body_iterator]
    assert any('PRIVATE_RESULT' in x for x in events)
    resp=await route_ns['stream_job_progress'](1,{'id':2,'is_admin':0}); denied=[x async for x in resp.body_iterator]
    assert not any('PRIVATE_RESULT' in x for x in denied)
asyncio.run(check())
print('CONFIRMED admin job SSE returns another owner private result; ordinary unrelated user denied')
print('5 offline defect probes passed; no network or production DB used')

# Exact production list comprehension drops valid technical questions by substring.
t=ast.parse((ROOT/'backend/app/agents/submit/extract.py').read_text())
blacklist=next(n for n in t.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='_EXTRACT_BLACKLIST' for x in n.targets))
filter_expr=next(n.value for n in ast.walk(t) if isinstance(n,ast.Assign) and isinstance(n.value,ast.ListComp))
filter_ns={};exec(compile(ast.Module(body=[blacklist],type_ignores=[]),'extract.py','exec'),filter_ns)
filter_ns['q_list']=['Redis持久化方案各有什么优缺点？','线程池有哪些优缺点？','解释TCP三次握手']
filtered=eval(compile(ast.Expression(filter_expr),'extract.py','eval'),filter_ns)
assert filtered==['解释TCP三次握手']
print('CONFIRMED exact extraction filter silently drops 2 valid technical questions containing 优缺点')

# Force the legal interleaving: withdraw reads pending, approve commits, withdraw writes.
c=database();r=ns['create_public_contribution_request'](c,'interview',1,1)
real_read=ns['_request_row'];interleaved=False

def interleaved_read(conn,request_id):
    global interleaved
    old=real_read(conn,request_id)
    if not interleaved:
        interleaved=True
        ns['approve_public_contribution'](conn,request_id,2)
    return old
ns['_request_row']=interleaved_read
r=ns['withdraw_public_contribution'](c,r['id'],1)
ns['_request_row']=real_read
assert r['status']=='withdrawn'
assert c.execute('SELECT count(*) FROM interview WHERE owner_id IS NULL').fetchone()[0]==1
assert c.execute("SELECT count(*) FROM analysis_queue WHERE status='pending'").fetchone()[0]==1
print('CONFIRMED approve/withdraw interleaving returns withdrawn while public projection and runnable queue remain')
print('TOTAL: 7 offline defect probes confirmed; interleaving forced at read boundary, no threaded timing assumption')
