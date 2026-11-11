import concurrent.futures
import json
import os
import subprocess
from pathlib import Path
root=Path(os.environ.get('TW_EVIDENCE_ROOT', '/tmp/pr34-final'))
seed=(root/'seed.log').read_text()
(root/'baseline.json').write_text(json.dumps(json.loads(next(x.split('=',1)[1] for x in seed.splitlines() if x.startswith('BASELINE_JSON='))),indent=2))
base=['docker','run','--rm','--network','container:tw-pr34-final-20261101','--read-only','--tmpfs','/tmp']
repo=str(Path(__file__).resolve().parents[2])
def run(name, source, args, fast=False):
    cmd=base+['-e','TW_TEST_DATABASE=test_pr34_final_'+name]
    if fast: cmd+=['-e','TW_FAST_HASH=1']
    cmd+=['-v',source+':/app:ro','-v',str(root/'runner.py')+':/runner.py:ro','-v',str(root)+':/evidence:ro','--entrypoint','python','trendwatch-litoral-web:latest','-B','/runner.py']+args
    with (root/(name+'.log')).open('w') as log:
        result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    print(name, 'exit',result.returncode,flush=True)
    return name,result.returncode
jobs=[('upgrade',repo+'/app',['scenario'],False),('branch-suite',repo+'/app',['test','core','--noinput'],True),('main-suite',str(root/'main/app'),['test','core','--noinput'],True),('directed',repo+'/app',['test','core.test_gestion_administradores','core.test_new_dashboard','core.test_indicadores_inicio','core.test_auth_views','core.test_navegacion_admin','core.test_perfil','core.test_integracion_pr24','core.test_identidad','--noinput'],True)]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results=list(pool.map(lambda job:run(*job),jobs))
for version,source in [('branch',repo+'/app'),('main',str(root/'main/app'))]:
    for check,args in [('check',['check']),('migrations',['makemigrations','--check','--dry-run'])]:
        results.append(run(version+'-'+check,source,args))
(root/'exit-codes.json').write_text(json.dumps(results,indent=2))
