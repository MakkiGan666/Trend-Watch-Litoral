"""Validación reproducible sólo en recursos creados por validar_generadas.sh."""
import io
import json
import os
import platform
import secrets
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from unittest.mock import patch

if os.environ.get('TW_GENERADAS_AISLADO') != '1' or sys.argv[1:] not in [['sqlite'], ['postgresql'], ['medir']]:
    raise SystemExit('Usar validar_generadas.sh; no admite conexiones externas.')
fase = sys.argv[1]
base = 'tw_buscador_desechable_generadas'
os.environ.update(DJANGO_SETTINGS_MODULE='mi_proyecto.settings', PYTHON_DOTENV_DISABLED='1',
                  SECRET_KEY=secrets.token_urlsafe(48), GEMINI_API_KEY='', DB_NAME=base,
                  DB_HOST='' if fase == 'sqlite' else '127.0.0.1', DB_PORT='5432',
                  DB_USER='postgres', DB_PASSWORD='', ALLOWED_HOSTS='testserver,localhost')
sys.path.insert(0, '/app')
from django.conf import settings
if fase == 'sqlite':
    settings.DATABASES['default']['NAME'] = '/tmp/buscador_generadas.sqlite3'
    settings.DATABASES['default']['TEST'] = {'NAME': '/tmp/test_generadas.sqlite3'}
import django
django.setup()
from django.apps import apps
from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ProjectState
from django.utils.translation import override
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db.models import Q
from django.db.models.functions import Coalesce
from core.models import Publicacion
from core.services.buscador import TextoComparable


def emitir(tipo, **datos):
    print(json.dumps({'tipo': tipo, 'fase': fase, **datos}, ensure_ascii=False), flush=True)


def comando(nombre, *args, **kwargs):
    log = io.StringIO()
    try:
        with redirect_stdout(log), redirect_stderr(log):
            call_command(nombre, *args, **kwargs)
    except BaseException:
        emitir('error', comando=nombre, detalle='\n'.join(linea[:600] for linea in log.getvalue().splitlines())[-7000:])
        raise
    return log.getvalue()


if fase != 'sqlite':
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()")
        assert cursor.fetchone() == (base, 'trendwatch-buscador:solo-pruebas-desechables:v1')
comando('migrate', interactive=False, verbosity=0)
assert not MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
emitir('instalacion', desde_cero=True, migraciones_pendientes=0, motor=connection.vendor)
if fase == 'sqlite':
    connection.close()
    with connection.cursor() as cursor:
        cursor.execute('SELECT tw_plegar_v1(%s)', ['EDUCACIO\u0301N NIÑO PINGÜINO'])
        assert cursor.fetchone()[0] == 'educacion niño pinguino'
    with transaction.atomic():
        p = Publicacion.objects.create(hash_origen='nueva-conexion', titulo='EDUCACIO\u0301N niño', contenido='PINGÜINO')
        r = Client().get('/api/publicaciones/buscar/', {'q': 'educacion pinguino'})
        assert r.status_code == 200 and r.json()['total'] == 1
        assert r.json()['resultados'][0]['id_publicacion_api'] == p.pk
        transaction.set_rollback(True)
    emitir('conexion_sqlite', reabierta=True, funcion_antes_de_buscar=True, escritura_y_busqueda=True)

# Control de diferencias de modelos: sólo se admiten los cuatro IDs previos.
executor = MigrationExecutor(connection)
# Igual que makemigrations: no comparar nombres lazy traducidos de auth/contenttypes.
with override(None):
    cambios = MigrationAutodetector(executor.loader.project_state(), ProjectState.from_apps(apps)).changes(graph=executor.loader.graph)
    operaciones = sorted((type(op).__name__, getattr(op, 'model_name', getattr(op, 'name', '')), getattr(op, 'name', ''))
                         for migraciones in cambios.values() for migracion in migraciones for op in migracion.operations)
esperadas = sorted(('AlterField', modelo, 'id') for modelo in ['publicaciontema', 'tematrend', 'userauditoria', 'votopublicacion'])
assert operaciones == esperadas, operaciones
salida = io.StringIO()
try:
    with redirect_stdout(salida), redirect_stderr(salida):
        call_command('makemigrations', '--check', '--dry-run', stdout=salida)
except SystemExit as error:
    assert error.code == 1
else:
    raise AssertionError('Se esperaba la diferencia de IDs preexistente')
emitir('control_modelos', diferencias_previas=operaciones, nuevas_ajenas=0,
       makemigrations_check_exit=1, solo_migracion_nueva='0011_publicacion_texto_busqueda')
comando('check', verbosity=0)
emitir('check', incidencias=0)

if fase != 'medir':
    etiquetas = ['core.test_buscador', 'core.test_texto_busqueda', 'core.test_fechas',
                 'core.test_publicacion_imagen', 'core.test_integracion_pr24',
                 'core.test_categorias_compat', 'core.test_perfil', 'core.test_navegacion_admin',
                 'core.test_new_dashboard', 'core.test_dashboard_localidades', 'core.test_localidades']
    if os.environ.get('TW_BUSCADOR_FRONTEND') in ('1', 'html'):
        etiquetas = ['core.test_busqueda_html', 'core.test_buscador', 'core.test_texto_busqueda',
                     'core.test_fechas', 'core.test_perfil', 'core.test_navegacion_admin',
                     'core.test_integracion_pr24', 'core.test_categorias_compat']
    if os.environ.get('TW_BUSCADOR_FRONTEND') == 'html':
        etiquetas = ['core.test_busqueda_html']
    if os.environ.get('TW_GENERADAS_LECTURAS') == '1':
        etiquetas = ['core.test_texto_busqueda.TextoBusquedaTests', 'core.test_comentarios']
    resultado = comando('test', *etiquetas, interactive=False, verbosity=1)
    emitir('pruebas', etiquetas=etiquetas, resumen=resultado.strip().splitlines()[-8:])
else:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version(), current_setting('server_encoding'), datcollate, datctype FROM pg_database WHERE datname=current_database()")
        entorno = cursor.fetchone()
        cursor.execute("SELECT attname, attgenerated FROM pg_attribute WHERE attrelid='\"Publicacion\"'::regclass AND attname IN ('titulo_busqueda','contenido_busqueda') ORDER BY attname")
        generadas = cursor.fetchall()
    emitir('entorno', python=platform.python_version(), django=django.get_version(), postgresql=entorno, columnas=generadas)
    assert not Publicacion.objects.exists()
    referencias = json.loads(Path('/referencia.json').read_text())
    referencias = {(d['filas'], d['q']): d for d in referencias
                   if d['tipo'] == 'medicion' and d['corpus'] == 'base_2040' and d['variante'] == 'A'}

    def legacy(terminos):
        qs = Publicacion.objects.alias(titulo_legacy=TextoComparable('titulo'), contenido_legacy=TextoComparable('contenido'))
        for termino in terminos:
            qs = qs.filter(Q(titulo_legacy__contains=termino) | Q(contenido_legacy__contains=termino))
        return qs.order_by(Coalesce('fecha_publicacion', 'fecha_captura').desc(nulls_last=True), '-pk')

    fecha = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    with transaction.atomic():
        for cantidad in [500, 5000]:
            existentes = Publicacion.objects.count()
            Publicacion.objects.bulk_create([
                Publicacion(hash_origen=f'medicion-{i}', titulo=f'Educación provincial {i}',
                            contenido='Información sobre educación y economía provincial. '*40 +
                            (' hallazgo singularis' if i % 499 == 0 else ''), fecha_captura=fecha,
                            fecha_publicacion=fecha if i % 2 else None)
                for i in range(existentes, cantidad)
            ])
            with connection.cursor() as cursor:
                cursor.execute('ANALYZE "Publicacion"')
            for consulta in ['educacion provincial', 'singularis', 'inexistentezz']:
                tiempos, cantidades = [], []
                for _ in range(6):
                    with CaptureQueriesContext(connection) as queries:
                        inicio = time.perf_counter()
                        respuesta = Client().get('/api/publicaciones/buscar/', {'q': consulta})
                        datos = respuesta.json()
                        tiempos.append((time.perf_counter()-inicio)*1000)
                    assert respuesta.status_code == 200
                    cantidades.append(len(queries))
                    assert all(q['sql'].startswith('SELECT') for q in queries)
                    for q in queries:
                        seleccion = q['sql'].split(' FROM ')[0]
                        assert 'titulo_busqueda' not in seleccion and 'contenido_busqueda' not in seleccion
                # Una comparación funcional con A; no se cronometra ni repite su investigación.
                with patch('core.services.buscador.publicaciones_coincidentes', legacy):
                    anterior = Client().get('/api/publicaciones/buscar/', {'q': consulta})
                assert anterior.status_code == 200 and anterior.json() == datos
                referencia = referencias[cantidad, consulta]
                assert referencia['total'] == datos['total']
                ms = median(tiempos[1:])
                emitir('medicion', filas=cantidad, q=consulta, total=datos['total'],
                       mediana_ms=round(ms, 3), repeticiones_ms=[round(t,3) for t in tiempos[1:]],
                       consultas=cantidades, equivalencia_a=True,
                       referencia_a_ms=referencia['endpoint_ms'], mejora=round(referencia['endpoint_ms']/ms, 2))
        transaction.set_rollback(True)
    assert not Publicacion.objects.exists()
    emitir('rollback_medicion', publicaciones=0)
emitir('fin', exito=True)
