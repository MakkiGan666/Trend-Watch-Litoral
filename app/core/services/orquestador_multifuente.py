"""H4.1: ejecución acotada y explícita; nunca habilita fuentes ni agenda ciclos."""
import time
import re
from dataclasses import replace

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection

from core.models import (AliasURLPublicacion, Categoria, Etiqueta, Locacion, ProcesamientoIAMultifuente,
                         Publicacion, PublicacionEtiqueta, PublicacionTema, RegistroDatos, Sentimiento, Tema)
from core.services import descarga_segura, fuentes_rss, gemini_multifuente, lector_rss
from core.services.extractor_articulos import analizar_articulo
from core.services.parametros import entero_positivo
from core.services.persistencia_multifuente import (EntradaPersistencia, buscar_publicacion_por_url,
                                                   persistir_lote, validar_entrada_persistencia)


_CONTADORES = ('descargadas', 'feeds_descargados', 'articulos_descargados', 'validas',
               'rechazadas', 'nuevas', 'previstas', 'duplicadas', 'pendientes_ia',
               'pendientes_ia_previstas')


class EsquemaMultifuenteIncompleto(ValueError):
    pass


def _tipo_sql(tipo):
    tipo = str(tipo).lower().strip().replace('character varying', 'varchar')
    tipo = re.sub(r'\bcharacter\b', 'char', tipo)
    return re.sub(r'\s+', '', tipo)


def _tipos_columnas(cursor, tabla, descripciones):
    if connection.vendor == 'postgresql':
        # OID solo no distingue varchar(4)/varchar(100); format_type incluye typmod.
        cursor.execute("""
            SELECT attname, pg_catalog.format_type(atttypid, atttypmod)
            FROM pg_catalog.pg_attribute
            WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped
        """, [connection.ops.quote_name(tabla)])
        return dict(cursor.fetchall())
    if connection.vendor == 'sqlite':
        return {c.name: c.type_code for c in descripciones}
    raise EsquemaMultifuenteIncompleto('Preflight multifuente sólo admite SQLite y PostgreSQL.')


def verificar_esquema_multifuente():
    """Preflight físico de sólo lectura: no usa ni ejecuta el plan de migraciones.

    Comprueba dependencias de persistencia/señales y las garantías de 0020/0021.
    No se cachea entre ejecuciones y no supone unicidad de datos históricos.
    """
    modelos = (Publicacion, RegistroDatos, AliasURLPublicacion, ProcesamientoIAMultifuente,
               Categoria, Tema, PublicacionTema, Etiqueta, PublicacionEtiqueta, Sentimiento, Locacion)
    versiones = {AliasURLPublicacion: '0020', ProcesamientoIAMultifuente: '0021'}
    problemas = []
    try:
        with connection.cursor() as cursor:
            tablas = set(connection.introspection.table_names(cursor))
            restricciones = {}
            for modelo in modelos:
                tabla = modelo._meta.db_table
                version = versiones.get(modelo, 'dependencia de 0020/0021')
                if tabla not in tablas:
                    problemas.append(f'falta tabla {tabla} ({version})')
                    continue
                descripciones = connection.introspection.get_table_description(cursor, tabla)
                columnas = {c.name: c for c in descripciones}
                faltantes = {f.column for f in modelo._meta.local_concrete_fields} - columnas.keys()
                if faltantes:
                    problemas.append(f'faltan columnas en {tabla} ({version}): ' + ', '.join(sorted(faltantes)))
                tipos = _tipos_columnas(cursor, tabla, descripciones)
                for campo in modelo._meta.local_concrete_fields:
                    if campo.column not in columnas:
                        continue
                    columna = columnas[campo.column]
                    referencia = f'{tabla}.{campo.column} ({version})'
                    # Django deja la nulabilidad de GeneratedField al backend; no se insertan.
                    if not campo.generated and columna.null_ok != campo.null:
                        problemas.append(f'nulabilidad incompatible en {referencia}: se esperaba null={campo.null}')
                    esperado, real = campo.db_type(connection), tipos.get(campo.column)
                    if _tipo_sql(real) != _tipo_sql(esperado):
                        problemas.append(f'tipo/longitud incompatible en {referencia}: esperado {esperado}, encontrado {real}')
                    if connection.vendor == 'postgresql' and campo.get_internal_type().endswith('AutoField'):
                        real_auto = connection.introspection.get_field_type(columna.type_code, columna)
                        if real_auto != campo.get_internal_type():
                            problemas.append(f'falta generación automática de ID en {referencia}')
                restricciones[modelo] = connection.introspection.get_constraints(cursor, tabla)

            def unica(modelo, campos, *, primaria=False):
                valores = restricciones.get(modelo, {}).values()
                return any((r.get('primary_key') if primaria else r.get('unique') or r.get('primary_key'))
                           and len(r['columns']) == len(campos) and set(r['columns']) == set(campos)
                           for r in valores)

            def fk(modelo):
                return any(r.get('foreign_key') == (Publicacion._meta.db_table, Publicacion._meta.pk.column)
                           and r['columns'] == ['publicacion_id']
                           for r in restricciones.get(modelo, {}).values())

            for modelo in modelos:
                if modelo in restricciones and not unica(modelo, [modelo._meta.pk.column], primaria=True):
                    problemas.append(f'PK incompatible en {modelo._meta.db_table} ({versiones.get(modelo, "dependencia de 0020/0021")})')
            if AliasURLPublicacion in restricciones:
                alias_unica = restricciones[AliasURLPublicacion].get('alias_url_unico_por_fuente', {})
                if not (alias_unica.get('unique') and not alias_unica.get('index')
                        and set(alias_unica.get('columns', [])) == {'fuente', 'url_normalizada'}):
                    problemas.append('falta unicidad (fuente, URL) de alias (0020)')
                if not fk(AliasURLPublicacion):
                    problemas.append('falta FK de alias a Publicacion (0020)')
            if ProcesamientoIAMultifuente in restricciones:
                if not unica(ProcesamientoIAMultifuente, ['publicacion_id'], primaria=True):
                    problemas.append('falta PK única por publicación en la cola (0021)')
                if not fk(ProcesamientoIAMultifuente):
                    problemas.append('falta FK de cola a Publicacion (0021)')
            if Publicacion in restricciones and not unica(Publicacion, ['hash_origen']):
                problemas.append('falta unicidad de hash_origen en Publicacion')
    except DatabaseError as exc:
        raise EsquemaMultifuenteIncompleto(
            'No se pudo verificar el esquema requerido por 0020/0021. No se inició la ingesta.'
        ) from exc
    if problemas:
        raise EsquemaMultifuenteIncompleto(
            'Esquema multifuente incompleto: ' + '; '.join(problemas) + '. No se inició la ingesta.')


def _resumen(identificador):
    return dict(fuente=identificador, **dict.fromkeys(_CONTADORES, 0), errores=[],
                entradas_rss_validas=0, repetidas=0, limitada=False, ia=None, registro_id=None,
                feed_valido=False, persistencia_incierta=0)


def _seleccionar(identificadores):
    if not isinstance(identificadores, (list, tuple)) or not identificadores:
        raise ValueError('Seleccioná al menos una fuente explícitamente.')
    catalogo = {f.identificador: f for f in fuentes_rss.obtener_fuentes(solo_habilitadas=False)}
    seleccionadas = []
    vistos = set()
    for identificador in identificadores:
        if not isinstance(identificador, str) or identificador not in catalogo:
            raise ValueError('Fuente desconocida.')
        fuente = catalogo[identificador]
        if not fuente.habilitada:
            raise ValueError(f'Fuente deshabilitada: {identificador}. Requiere revisión del catálogo fuera del comando.')
        if identificador not in vistos:
            descarga_segura.validar_url(fuente.feed, fuente=fuente)
            seleccionadas.append(fuente)
            vistos.add(identificador)
    return seleccionadas


def _error(resumen, etapa, codigo, *, indice=None, url=None):
    resumen['errores'].append(dict(etapa=etapa, codigo=codigo, indice=indice, url=url))


def ejecutar_ingesta_multifuente(identificadores, *, limite_por_fuente=3, limite_total=10,
                                dry_run=False, procesar_ia=False, limite_ia=5, cliente_ia=None):
    """Descargadas cuenta respuestas RSS+HTML; válidas son entradas reconocidas o aceptadas por H3.1.

    El límite cuenta entradas RSS admitidas, incluidas repeticiones, y consultas
    canónicas adicionales no presupuestadas por otra entrada ni servidas de caché;
    la preconsulta de identidad evita HTML de noticias ya guardadas y la caché
    evita repetir URL normalizada dentro de la ejecución. No descarga imágenes.
    Dry-run permite HTTP seguro, consulta identidad y valida persistencia, sin
    escrituras ni Gemini. Las previsiones se separan de altas/pendientes reales.
    """
    for nombre, valor in (('limite_por_fuente', limite_por_fuente), ('limite_total', limite_total),
                          ('limite_ia', limite_ia)):
        entero_positivo(valor, nombre)
    if limite_por_fuente > 30 or limite_total > 100 or limite_ia > 20:
        raise ValueError('Máximos: 30 noticias/fuente, 100 noticias/ejecución, 20 llamadas IA.')
    if type(dry_run) is not bool or type(procesar_ia) is not bool:
        raise ValueError('dry_run y procesar_ia deben ser booleanos.')
    seleccionadas = _seleccionar(identificadores)
    if not dry_run and (connection.in_atomic_block or not connection.get_autocommit()):
        raise ValueError('Ejecutá el orquestador sin transacción externa.')
    verificar_esquema_multifuente()
    resumenes = []
    restantes = limite_total
    ia_restantes = limite_ia
    cache = {}  # Sólo extracciones persistibles y fallos; los bytes van a cache_http.
    cache_http = {}

    def descargar(url, fuente, resumen, tipo):
        clave = (fuente.identificador, url)
        if clave not in cache_http:
            try:
                cache_http[clave] = descarga_segura.descargar(url, fuente=fuente)
                resumen['descargadas'] += 1
                resumen[tipo] += 1
            except Exception as exc:
                cache_http[clave] = exc
        valor = cache_http[clave]
        if isinstance(valor, Exception):
            raise valor
        return valor

    for fuente in seleccionadas:
        resumen = _resumen(fuente.identificador)
        resumenes.append(resumen)
        if restantes == 0:
            resumen['limitada'] = True
            continue
        try:
            datos = descargar(fuente.feed, fuente, resumen, 'feeds_descargados')
            feed = lector_rss.analizar_rss(datos, fuente)
            resumen['feed_valido'] = True
        except Exception as exc:
            _error(resumen, 'rss', type(exc).__name__)
            continue
        resumen['entradas_rss_validas'] = len(feed.noticias)
        resumen['rechazadas'] += len(feed.rechazos)
        for indice, _ in feed.rechazos:
            _error(resumen, 'rss_entrada', 'entrada_invalida', indice=indice)
        cupo = min(limite_por_fuente, fuente.limite_noticias, restantes)
        noticias = feed.noticias[:cupo]
        urls_presupuestadas = {n.url for n in noticias}
        extras_fuente = 0
        resumen['limitada'] = len(feed.noticias) > cupo
        restantes -= len(noticias)
        candidatos, indices, conocidas = [], [], []
        rechazados_rss = {i for i, _ in feed.rechazos}
        indices_rss = [i for i in range(len(feed.noticias) + len(feed.rechazos)) if i not in rechazados_rss]
        for indice, noticia in zip(indices_rss, noticias):
            try:
                pk = buscar_publicacion_por_url(noticia)
                if pk is not None and AliasURLPublicacion.objects.filter(
                    publicacion_id=pk, fuente=fuente.identificador, url_normalizada=noticia.url
                ).exists():
                    resumen['validas'] += 1
                    resumen['duplicadas'] += 1
                    conocidas.append(dict(estado='DUPLICADA', publicacion_id=pk))
                    continue
                actual = noticia
                visitadas = set()
                while True:
                    clave = (fuente.identificador, actual.url)
                    visitadas.add(actual.url)
                    if clave in cache:
                        resumen['repetidas'] += 1
                        articulo = cache[clave]
                    else:
                        try:
                            html = descargar(actual.url, fuente, resumen, 'articulos_descargados')
                            articulo = analizar_articulo(html, actual, fuente)
                        except Exception as exc:
                            cache[clave] = exc
                            raise
                    if isinstance(articulo, Exception):
                        raise articulo
                    try:
                        validar_entrada_persistencia(EntradaPersistencia(noticia, articulo))
                    except (ValueError, ValidationError):
                        apto = False
                    else:
                        apto = True
                    if apto:
                        # Validar también al reutilizar: los fallbacks RSS pueden variar.
                        cache[clave] = articulo
                        cache[(fuente.identificador, articulo.url_canonica)] = articulo
                        cache[(fuente.identificador, noticia.url)] = articulo
                        break
                    canonica = lector_rss.normalizar_url(articulo.url_canonica, fuente)
                    if canonica in visitadas:
                        break
                    destino = (fuente.identificador, canonica)
                    if destino not in cache_http and destino not in cache and canonica not in urls_presupuestadas:
                        if restantes == 0 or len(noticias) + extras_fuente >= min(limite_por_fuente, fuente.limite_noticias):
                            resumen['limitada'] = True
                            break
                        restantes -= 1
                        extras_fuente += 1
                        urls_presupuestadas.add(canonica)
                    # Nueva URL/base, pero conserva título y fecha de fallback del RSS.
                    actual = replace(noticia, url=canonica)
                candidatos.append(EntradaPersistencia(noticia, articulo))
                indices.append(indice)
            except Exception as exc:
                resumen['rechazadas'] += 1
                _error(resumen, 'articulo', type(exc).__name__, indice=indice, url=noticia.url)
        recibo = dict(dry_run=dry_run, registro_id=None, noticias=[])
        if candidatos:
            try:
                recibo = persistir_lote(candidatos, dry_run=dry_run)
                resumen['registro_id'] = recibo['registro_id']
                resumen['nuevas'] = recibo['capturados']
                resumen['previstas'] = recibo['previstos']
                resumen['duplicadas'] += recibo['omitidas']
                resumen['validas'] += len(candidatos) - len(recibo['errores'])
                resumen['rechazadas'] += len(recibo['errores'])
                for error in recibo['errores']:
                    _error(resumen, 'persistencia', error['codigo'], indice=indices[error['indice']])
            except Exception as exc:
                resumen['persistencia_incierta'] += len(candidatos)
                _error(resumen, 'persistencia', type(exc).__name__)
        recibo['noticias'].extend(conocidas)
        if procesar_ia and not dry_run and ia_restantes:
            try:
                if ia_restantes < limite_ia:
                    time.sleep(12)  # Conserva la pausa H3.2 también entre fuentes.
                ia = gemini_multifuente.procesar_nuevas(recibo, batch_size=ia_restantes, cliente=cliente_ia)
                resumen['ia'] = ia
                ia_restantes -= ia['llamadas']
                for error in ia['errores']:
                    _error(resumen, 'gemini', error['codigo'])
            except Exception as exc:
                _error(resumen, 'gemini', type(exc).__name__)
        ids = {n.get('publicacion_id') for n in recibo['noticias'] if n.get('publicacion_id') is not None}
        if ids:
            try:
                resumen['pendientes_ia'] = Publicacion.objects.filter(
                    gemini_multifuente.filtro_cliente_global(), pk__in=ids, procesado_ia=False,
                    procesamiento_ia_multifuente__isnull=False).count()
            except Exception as exc:
                _error(resumen, 'resumen', type(exc).__name__)
        resumen['pendientes_ia_previstas'] = resumen['previstas']
    resultado = dict(dry_run=dry_run, procesar_ia=procesar_ia and not dry_run, fuentes=resumenes,
                     **{campo: sum(r[campo] for r in resumenes) for campo in _CONTADORES})
    resultado['errores'] = [dict(fuente=r['fuente'], **e) for r in resumenes for e in r['errores']]
    resultado['limitada'] = any(r['limitada'] for r in resumenes)
    resultado['estado'] = ('PARCIAL' if any(r['feed_valido'] for r in resumenes) else 'FALLO') if resultado['errores'] else 'EXITO'
    return resultado
