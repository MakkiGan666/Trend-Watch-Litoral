"""Sugerencias públicas: títulos tokenizados en SQL, nunca corpus en Python."""
from django.db import connection
from django.db.models import Case, IntegerField, Q, Value, When
from django.urls import reverse

from core.busqueda_texto_v1 import BASES_V1, VOCALES_V1
from core.busqueda_texto_v1 import plegar_v1
from .buscador import publicaciones_coincidentes, validar_consulta


def sugerir(valor):
    consulta, terminos = validar_consulta(valor)
    # La búsqueda tradicional exige todos los términos. Completar sólo la última
    # palabra conserva ese contexto; las anteriores se mantienen en la selección.
    palabras_consulta = consulta.split()
    prefijo = plegar_v1(palabras_consulta[-1])
    contexto = palabras_consulta[:-1]
    anteriores = publicaciones_coincidentes(list(dict.fromkeys(plegar_v1(p) for p in contexto)))
    longitud_disponible = 150 - len(' '.join(contexto)) - bool(contexto)
    origen, parametros = anteriores.order_by().values('id_publicacion_api', 'titulo', 'fecha_publicacion', 'fecha_captura').query.sql_with_params()
    if connection.vendor == 'postgresql':
        sql = f"""
        WITH origen AS ({origen}), palabras AS (
            SELECT id_publicacion_api AS id, COALESCE(fecha_publicacion, fecha_captura) AS fecha,
                   palabra, translate(lower(palabra), %s, %s) AS clave
            FROM origen CROSS JOIN LATERAL
                 regexp_split_to_table(normalize(titulo, NFC), '[^[:alnum:]_]+') AS palabra
        )
        SELECT MIN(palabra), COUNT(DISTINCT id) AS frecuencia
        FROM palabras WHERE clave LIKE %s ESCAPE '\\' AND length(palabra) BETWEEN 2 AND %s
        GROUP BY clave ORDER BY frecuencia DESC, MAX(fecha) DESC NULLS LAST, clave ASC LIMIT 5
        """
        parametros = [*parametros, VOCALES_V1, BASES_V1, _prefijo_like(prefijo), longitud_disponible]
    elif connection.vendor == 'sqlite':
        # Función de tokenización exclusiva de compatibilidad SQLite; PostgreSQL
        # usa su función SQL nativa. Registro por conexión, sin tablas auxiliares.
        import json
        import re
        import unicodedata
        connection.ensure_connection()
        connection.connection.create_function('tw_palabras', 1, lambda titulo: json.dumps(
            re.findall(r'\w+', unicodedata.normalize('NFC', titulo)), ensure_ascii=False), deterministic=True)
        sql = f"""
        WITH origen AS ({origen}), palabras AS (
            SELECT id_publicacion_api AS id, COALESCE(fecha_publicacion, fecha_captura) AS fecha,
                   value AS palabra, tw_plegar_v1(value) AS clave
            FROM origen, json_each(tw_palabras(titulo))
        )
        SELECT MIN(palabra), COUNT(DISTINCT id) AS frecuencia
        FROM palabras WHERE clave LIKE %s ESCAPE '\\' AND length(palabra) BETWEEN 2 AND %s
        GROUP BY clave ORDER BY frecuencia DESC, MAX(fecha) DESC NULLS LAST, clave ASC LIMIT 5
        """
        parametros = [*parametros, _prefijo_like(prefijo), longitud_disponible]
    else:
        raise NotImplementedError('Motor de búsqueda no soportado')
    with connection.cursor() as cursor:
        cursor.execute(sql, parametros)
        palabras = cursor.fetchall()
    # Prioridad por número de términos en título; filtro y desempates se
    # comparten con el buscador. Sólo cuatro filas, sin COUNT ni N+1.
    puntuacion = Value(0, output_field=IntegerField())
    for termino in terminos:
        puntuacion = puntuacion + Case(When(Q(titulo_busqueda__contains=termino), then=Value(1)), default=Value(0), output_field=IntegerField())
    noticias = publicaciones_coincidentes(terminos).annotate(puntos=puntuacion)
    noticias = noticias.order_by('-puntos', *noticias.query.order_by).values('pk', 'titulo')[:4]
    return {
        'consulta': consulta,
        'terminos': [{'texto': palabra, 'consulta': ' '.join([*contexto, palabra])} for palabra, _ in palabras],
        'noticias': [{'titulo': p['titulo'], 'url': reverse('noticia', kwargs={'pk': p['pk']})} for p in noticias],
    }


def _prefijo_like(valor):
    return valor.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
