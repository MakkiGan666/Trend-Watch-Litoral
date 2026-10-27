"""Pruebas/medición acotadas; sólo mediante el launcher hermano."""
import io
import json
import os
import platform
import secrets
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from statistics import median

if os.environ.get('TW_AUTOCOMPLETADO_AISLADO') != '1' or sys.argv[1:] not in [['postgresql'], ['sqlite'], ['medir']]:
    raise SystemExit('Usar validar_autocompletado.sh; no acepta DSN')
fase = sys.argv[1]
os.environ.update(DJANGO_SETTINGS_MODULE='mi_proyecto.settings', PYTHON_DOTENV_DISABLED='1',
                  SECRET_KEY=secrets.token_urlsafe(48), DB_HOST='' if fase == 'sqlite' else '127.0.0.1',
                  DB_NAME='tw_autocompletado_desechable', DB_PORT='5432', DB_USER='postgres', DB_PASSWORD='',
                  GEMINI_API_KEY='', ALLOWED_HOSTS='testserver,localhost')
sys.path.insert(0, '/app')
from django.conf import settings
if fase == 'sqlite': settings.DATABASES['default']['NAME'] = '/tmp/autocompletado.sqlite3'
import django
django.setup()
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client
from django.db.migrations.executor import MigrationExecutor
from core.models import Publicacion

def emitir(tipo, **datos):
    print(json.dumps({'tipo': tipo, 'fase': fase, **datos}, ensure_ascii=False), flush=True)

def comando(*args, **kwargs):
    salida = io.StringIO()
    try:
        with redirect_stdout(salida), redirect_stderr(salida): call_command(*args, **kwargs)
    except BaseException:
        emitir('error', comando=args[0], detalle='\n'.join(l[:350] for l in salida.getvalue().splitlines())[-5000:])
        raise
    return salida.getvalue()

if fase != 'sqlite':
    with connection.cursor() as c:
        c.execute("SELECT current_database(), shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()")
        assert c.fetchone() == ('tw_autocompletado_desechable', 'trendwatch-autocompletado:solo-desechable:v1')
comando('migrate', interactive=False, verbosity=0)
assert not MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
comando('check', verbosity=0)
emitir('check', django=django.get_version(), python=platform.python_version(), incidencias=0, migraciones_pendientes=0)
if fase != 'medir':
    etiquetas = ['core.test_sugerencias', 'core.test_buscador', 'core.test_busqueda_html',
                 'core.test_texto_busqueda', 'core.test_fechas', 'core.test_comentarios',
                 'core.test_valoraciones', 'core.test_navegacion_admin']
    resultado = comando('test', *etiquetas, interactive=False, verbosity=1)
    emitir('pruebas', etiquetas=etiquetas, resumen=resultado.strip().splitlines()[-8:])
else:
    with connection.cursor() as c:
        c.execute("SELECT version(), current_setting('server_encoding'), datcollate, datctype FROM pg_database WHERE datname=current_database()")
        emitir('entorno', postgresql=c.fetchone(), cpu=platform.processor(), sistema=platform.platform())
    assert not Publicacion.objects.exists()
    fecha = datetime(2026,10,23,12,tzinfo=timezone.utc)
    with transaction.atomic():
        for cantidad in (500,5000):
            existentes = Publicacion.objects.count()
            Publicacion.objects.bulk_create([Publicacion(hash_origen=f'medicion-{i}', titulo=f'Educación provincial {i}',
                contenido='Información sobre educación y economía provincial. '*40 + (' hallazgo singularis' if i % 499 == 0 else ''),
                fecha_captura=fecha, fecha_publicacion=fecha if i % 2 else None) for i in range(existentes,cantidad)])
            with connection.cursor() as c: c.execute('ANALYZE "Publicacion"')
            for q in ('ed','singularis','inexistentezz','educacion pro'):
                tiempos,sqls,counts,respuestas = [],[],[],[]
                for repeticion in range(6):
                    sentencias=[]
                    def medir(execute, sql, params, many, context):
                        inicio=time.perf_counter()
                        try: return execute(sql,params,many,context)
                        finally: sentencias.append((sql,(time.perf_counter()-inicio)*1000))
                    with connection.execute_wrapper(medir):
                        inicio=time.perf_counter()
                        respuesta=Client().get('/api/publicaciones/sugerencias/', {'q':q})
                        datos=respuesta.json()
                        tiempos.append((time.perf_counter()-inicio)*1000)
                    assert respuesta.status_code==200 and len(sentencias)==2
                    assert all(s.lstrip().startswith(('WITH','SELECT')) for s,_ in sentencias)
                    sqls.append([t for _,t in sentencias]);counts.append(len(sentencias));respuestas.append(datos)
                assert all(d==respuestas[0] for d in respuestas)
                emitir('medicion',filas=cantidad,q=q,mediana_endpoint_ms=round(median(tiempos[1:]),3),
                    terminos_sql_ms=round(median(t[0] for t in sqls[1:]),3),noticias_sql_ms=round(median(t[1] for t in sqls[1:]),3),
                    repeticiones_ms=[round(t,3) for t in tiempos[1:]],consultas=counts,
                    terminos=len(datos['terminos']),noticias=len(datos['noticias']),equivalencia_repeticiones=True)
        transaction.set_rollback(True)
    assert not Publicacion.objects.exists()
    emitir('rollback', publicaciones=0)
emitir('fin', exito=True)
