"""Diagnóstico explícito, transaccional y exclusivo de PostgreSQL desechable."""
import json
import platform
import statistics
import time

import django
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import Publicacion
from core.services.buscador import BASES, VOCALES, publicaciones_coincidentes, validar_consulta

MARCA_BASE = 'trendwatch-buscador:solo-pruebas-desechables:v1'
PREFIJO_BASE = 'tw_buscador_desechable_'


def verificar_base_desechable():
    """Fallar antes de toda escritura, incluso si la base real está vacía."""
    if connection.vendor != 'postgresql':
        raise CommandError('El diagnóstico requiere PostgreSQL desechable.')
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), shobj_description(oid, 'pg_database') "
                       'FROM pg_database WHERE datname = current_database()')
        nombre, marca = cursor.fetchone()
    if not nombre.startswith(PREFIJO_BASE) or marca != MARCA_BASE:
        raise CommandError('Base rechazada: se requieren prefijo de pruebas y marca explícita de base desechable.')
    if Publicacion.objects.exists():
        raise CommandError('La base desechable debe estar vacía de publicaciones.')


def mediana(valores):
    return round(statistics.median(valores), 3)


def explicar(sql, parametros):
    tiempos = []
    with connection.cursor() as cursor:
        for _ in range(3):
            cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, parametros)
            plan = cursor.fetchone()[0][0]
            tiempos.append(plan['Execution Time'])
    return {'ms': tiempos, 'mediana_ms': mediana(tiempos), 'plan': plan}


def componentes():
    # Identificadores y expresiones fijos; no se acepta SQL del usuario.
    campo = 'contenido'
    nfc = f'CASE WHEN {campo} IS NFC NORMALIZED THEN {campo} ELSE normalize({campo}, NFC) END'
    reemplazos = f'lower({nfc})'
    parametros = []
    for vocal, base in zip(VOCALES, BASES):
        reemplazos = f'replace({reemplazos}, %s, %s)'
        parametros.extend([vocal, base])
    regex = f'lower({nfc})'
    parametros_regex = []
    for base in dict.fromkeys(BASES):
        grupo = ''.join(v for v, b in zip(VOCALES, BASES) if b == base)
        regex = f"regexp_replace({regex}, %s, %s, 'g')"
        parametros_regex.extend(['[' + grupo + ']', base])
    return {
        'like': (campo, []),
        'nfc_directo_like': (f'normalize({campo}, NFC)', []),
        'nfc_condicional_like': (nfc, []),
        'lower_like': (f'lower({campo})', []),
        'translate_like': (f'translate({campo}, %s, %s)', [VOCALES, BASES]),
        'nfc_lower_like': (f'lower({nfc})', []),
        'completo_translate_like': (f'translate(lower({nfc}), %s, %s)', [VOCALES, BASES]),
        'completo_replace_like': (reemplazos, parametros),
        'completo_regex_fija_like': (regex, parametros_regex),
    }


class Command(BaseCommand):
    help = 'Diagnostica 500/5000 noticias sólo en una base PostgreSQL marcada; revierte los datos.'

    def add_arguments(self, parser):
        parser.add_argument('--base-desechable', action='store_true', required=True)
        parser.add_argument('--etiqueta', default='actual')

    def emitir(self, tipo, **datos):
        self.stdout.write(json.dumps({'tipo': tipo, **datos}, ensure_ascii=False))
        self.stdout.flush()

    def handle(self, *args, **options):
        # También exigir el flag al invocar call_command programáticamente.
        if not options.get('base_desechable'):
            raise CommandError('Se requiere --base-desechable.')
        verificar_base_desechable()
        with connection.cursor() as cursor:
            cursor.execute("SELECT version(), current_setting('server_encoding'), "
                           "current_setting('shared_buffers'), current_setting('work_mem'), "
                           "current_setting('max_parallel_workers_per_gather')")
            entorno = dict(zip(['postgresql', 'encoding',
                               'shared_buffers', 'work_mem', 'max_parallel_workers_per_gather'], cursor.fetchone()))
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            postgis = cursor.fetchone()
            entorno['postgis'] = postgis[0] if postgis else None
            cursor.execute('SELECT datlocprovider, datcollate, datctype FROM pg_database WHERE datname=current_database()')
            entorno['locale_base'] = cursor.fetchone()
        self.emitir('entorno', etiqueta=options['etiqueta'], python=platform.python_version(),
                    django=django.get_version(), **entorno)
        with transaction.atomic():
            for cantidad in [500, 5000]:
                existentes = Publicacion.objects.count()
                Publicacion.objects.bulk_create([
                    Publicacion(hash_origen=f'medicion-{i}', titulo=f'Educación provincial {i}',
                                contenido=('Información sobre educación y economía provincial. '*40) +
                                (' hallazgo singularis' if i % 499 == 0 else ''))
                    for i in range(existentes, cantidad)
                ])
                with connection.cursor() as cursor:
                    cursor.execute('ANALYZE "Publicacion"')
                for consulta in ['educacion provincial', 'singularis', 'inexistentezz']:
                    tiempos, cantidades = [], []
                    conteo_sql = []

                    def capturar_count(execute, sql, params, many, context):
                        if sql.startswith('SELECT COUNT('):
                            conteo_sql.append((sql, params))
                        return execute(sql, params, many, context)

                    for _ in range(6):
                        with connection.execute_wrapper(capturar_count), CaptureQueriesContext(connection) as queries:
                            inicio = time.perf_counter()
                            respuesta = Client().get(reverse('buscar_publicaciones'), {'q': consulta})
                            tiempos.append((time.perf_counter()-inicio)*1000)
                        cantidades.append(len(queries))
                        if respuesta.status_code != 200:
                            raise CommandError(str(respuesta.content))
                    self.emitir('endpoint', etiqueta=options['etiqueta'], noticias=cantidad,
                                caracteres_contenido=2040, q=consulta, total=respuesta.json()['total'],
                                ms_calientes=[round(t, 3) for t in tiempos[1:]],
                                mediana_ms=mediana(tiempos[1:]), consultas=cantidades)
                    _, terminos = validar_consulta(consulta)
                    pagina_sql = publicaciones_coincidentes(terminos)[:20].query.sql_with_params()
                    for operacion, (sql, parametros) in [('count', conteo_sql[-1]), ('pagina', pagina_sql)]:
                        self.emitir('sql', etiqueta=options['etiqueta'], noticias=cantidad, q=consulta,
                                    operacion=operacion, sql=sql, parametros=parametros, **explicar(sql, parametros))
                if cantidad == 5000:
                    for componente, (expresion, parametros) in componentes().items():
                        sql = 'SELECT count(*) FROM "Publicacion" WHERE ' + expresion + ' LIKE %s'
                        self.emitir('componente', etiqueta=options['etiqueta'], noticias=cantidad,
                                    componente=componente, sql=sql, parametros=[*parametros, '%inexistentezz%'],
                                    **explicar(sql, [*parametros, '%inexistentezz%']))
            transaction.set_rollback(True)
