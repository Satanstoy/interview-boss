import os,sqlite3,tempfile,sys
original=sqlite3.connect
def guarded(database,*args,**kwargs):
    value=str(database)
    if value != ':memory:' and not value.startswith('/tmp/') and not ('mode=memory' in value):
        raise RuntimeError('Audit forbids non-test SQLite access')
    return original(database,*args,**kwargs)
sqlite3.connect=guarded
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
sys.path.insert(0,os.getcwd()+'/backend')
import pytest
raise SystemExit(pytest.main(['-p','pytest_asyncio.plugin','-q','backend/tests/services/test_public_contributions_materialize.py','backend/tests/infra/test_db_retention.py']))
