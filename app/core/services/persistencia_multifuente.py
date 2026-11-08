"""H3.1: persistencia sin red ni IA, separada del circuito de El Territorio.

Acepta NoticiaRSS con contenido completo, ArticuloExtraido suficiente o
EntradaPersistencia(RSS, HTML) para conservar sección e identidad del RSS.
Identidad nueva: SHA-256 de ['rss:v1', fuente_id, URL normalizada]. No se
reescriben hashes, URLs ni identificadores históricos. Un RegistroDatos audita
cada ejecución real, incluidos reintentos; dry-run no crea ningún registro.
"""
from dataclasses import dataclass
from datetime import datetime
import json
import hashlib

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from core.models import AliasURLPublicacion, ProcesamientoIAMultifuente, Publicacion, RegistroDatos
from core.services import descarga_segura
from core.services.clasificacion import clasificar_lote, vincular_categoria_por_nombre
from core.services.etiquetas import sugerir_etiquetas
from core.services.extractor_articulos import ArticuloExtraido, _suficiente
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS, normalizar_url
from core.services.scraper import generar_hash


@dataclass(frozen=True)
class EntradaPersistencia:
    noticia: NoticiaRSS
    articulo: ArticuloExtraido


def _texto(valor, campo, *, obligatorio=False):
    if (not isinstance(valor, str) or (obligatorio and not valor.strip())
            or any(ord(c) < 32 and c not in '\n\r\t' or ord(c) == 127 for c in valor)):
        raise ValueError(f'{campo} inválido.')
    return valor


def _fecha(valor):
    if valor is not None and (not isinstance(valor, datetime) or timezone.is_naive(valor)):
        raise ValueError('Fecha inválida: usar datetime con zona horaria o None.')
    return valor


def _fuente(entrada):
    fuente = next((f for f in FUENTES_RSS if f.identificador == entrada.fuente_id), None)
    if fuente is None or entrada.fuente != fuente.nombre:
        raise ValueError('Fuente desconocida o inconsistente.')
    descarga_segura.validar_url(fuente.feed, fuente=fuente)
    return fuente


def _preparar(entrada):
    rss = entrada.noticia if type(entrada) is EntradaPersistencia else None
    actual = entrada.articulo if rss is not None else entrada
    if rss is not None and type(actual) is not ArticuloExtraido:
        raise ValueError('La pareja requiere RSS y ArticuloExtraido.')
    if type(actual) not in (NoticiaRSS, ArticuloExtraido):
        raise ValueError('Se requiere una noticia normalizada H2.2/H2.3.')
    fuente = _fuente(actual)
    seccion = ''
    if type(actual) is NoticiaRSS:
        url = actual.url
        contenido = actual.contenido_completo  # Nunca sustituir por resumen.
        imagen = ''
        seccion = _texto(actual.seccion, 'Sección')
    else:
        if actual.suficiente is not True:
            raise ValueError('Extracción HTML insuficiente.')
        url = actual.url_canonica
        contenido = actual.cuerpo
        imagen = actual.imagen_principal
    url = normalizar_url(url, fuente)
    identidad = url
    aliases = {url}
    if rss is not None:
        if type(rss) is not NoticiaRSS or _fuente(rss) != fuente:
            raise ValueError('RSS y artículo pertenecen a fuentes diferentes.')
        _texto(rss.titulo, 'Título RSS', obligatorio=True)
        if len(rss.titulo) > Publicacion._meta.get_field('titulo').max_length:
            raise ValueError('Título RSS demasiado largo.')
        _fecha(rss.fecha)
        identidad = normalizar_url(rss.url, fuente)
        if len(identidad) > Publicacion._meta.get_field('url').max_length:
            raise ValueError('URL RSS demasiado larga.')
        aliases.add(identidad)
        seccion = _texto(rss.seccion, 'Sección')
    titulo = _texto(actual.titulo, 'Título', obligatorio=True)
    contenido = _texto(contenido, 'Contenido', obligatorio=True)
    if not _suficiente(contenido) or len(contenido.encode('utf-8')) > fuente.max_bytes:
        raise ValueError('Contenido insuficiente o demasiado grande.')
    _texto(imagen, 'Imagen')
    if imagen:
        imagen = normalizar_url(imagen, fuente)
    datos = dict(fuente=fuente.nombre, titulo=titulo, contenido=contenido,
                 url=url, imagen_url=imagen, fecha_publicacion=_fecha(actual.fecha),
                 procesado_ia=False)
    for campo in ('fuente', 'titulo', 'url', 'imagen_url'):
        if len(datos[campo]) > Publicacion._meta.get_field(campo).max_length:
            raise ValueError(f'{campo} demasiado largo.')
    datos['hash_origen'] = _hash_identidad(fuente, identidad)
    return fuente, datos, aliases, seccion


def _hash_identidad(fuente, url):
    serializada = json.dumps(['rss:v1', fuente.identificador, url],
                            ensure_ascii=False, separators=(',', ':'))
    return generar_hash(serializada)


def hash_identidad_fuente_url(fuente, url_normalizada):
    """Hash compartido por el pipeline completo y las fichas RSS H5.4."""
    return _hash_identidad(fuente, url_normalizada)


def buscar_publicacion_por_url(noticia):
    """Preconsulta sin escrituras ni necesidad de HTML; no oculta conflictos históricos."""
    if type(noticia) is not NoticiaRSS:
        raise ValueError('Se requiere NoticiaRSS.')
    fuente = _fuente(noticia)
    url = normalizar_url(noticia.url, fuente)
    return _existente(fuente, {'hash_origen': _hash_identidad(fuente, url)}, {url})


class ConflictoIdentidad(ValueError):
    """Alias conocidos apuntan a publicaciones distintas: nunca fusionar solos."""


def _existente(fuente, datos, aliases):
    ids = set()
    for pk, nombre in AliasURLPublicacion.objects.filter(
        fuente=fuente.identificador, url_normalizada__in=aliases
    ).values_list('publicacion_id', 'publicacion__fuente'):
        if nombre != fuente.nombre:
            raise ConflictoIdentidad('Alias asociado a otra fuente.')
        ids.add(pk)
    existente = Publicacion.objects.filter(hash_origen=datos['hash_origen']).values('pk', 'fuente').first()
    if existente is not None:
        if existente['fuente'] != fuente.nombre:
            raise ConflictoIdentidad('Conflicto de hash entre fuentes.')
        ids.add(existente['pk'])
    # No suponer que los históricos son únicos ni modificar sus hashes o URLs.
    for pk, url in Publicacion.objects.filter(fuente=fuente.nombre).values_list('pk', 'url').iterator():
        try:
            if normalizar_url(url, fuente) in aliases:
                ids.add(pk)
        except ValueError:
            continue
    if len(ids) > 1:
        raise ConflictoIdentidad('Alias asociados a varias publicaciones; requieren revisión.')
    return next(iter(ids), None)


def resolver_publicacion_por_identidad(fuente, hash_origen, aliases):
    """Resuelve alias/hash/URLs históricas sin fusionar ni editar publicaciones."""
    return _existente(fuente, {'hash_origen': hash_origen}, set(aliases))


def _bloquear_fuente(fuente):
    """PostgreSQL serializa decisiones y alta de alias, incluso sin filas previas.

    Bloqueo de transacción por fuente: no depende de procesos Python ni de que
    los escritores conozcan los mismos alias. Se libera al commit/rollback.
    Read Committed permite releer lo confirmado por el escritor anterior.
    SQLite se protege con su bloqueo de escritura y el UNIQUE de alias; ante
    contención puede informar un error reintentable, nunca guardar media noticia.
    """
    if connection.vendor == 'postgresql':
        clave = int.from_bytes(hashlib.sha256(
            ('trendwatch:rss:fuente:v1:' + fuente.identificador).encode()
        ).digest()[:8], 'big', signed=True)
        with connection.cursor() as cursor:
            cursor.execute('SHOW transaction_isolation')
            if cursor.fetchone()[0] != 'read committed':
                raise ValueError('La persistencia RSS requiere Read Committed en PostgreSQL.')
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [clave])


def bloquear_fuente_rss(fuente):
    """Comparte el lock transaccional de identidad con H3.1/H4.1."""
    return _bloquear_fuente(fuente)


def _vincular_aliases(fuente, aliases, pk):
    for url in sorted(aliases):
        alias, _ = AliasURLPublicacion.objects.get_or_create(
            fuente=fuente.identificador, url_normalizada=url, defaults={'publicacion_id': pk})
        if alias.publicacion_id != pk:
            raise ConflictoIdentidad('El alias ya pertenece a otra publicación.')


def vincular_aliases_rss(fuente, aliases, publicacion_id):
    """Vincula aliases normalizados bajo la restricción UNIQUE existente."""
    return _vincular_aliases(fuente, aliases, publicacion_id)


def _clasificar_y_validar(datos, seccion):
    clasificacion, = clasificar_lote([dict(titulo=datos['titulo'], contenido=datos['contenido'],
                                          seccion=seccion)], usar_ia=False)
    publicacion = Publicacion(**datos, departamento=clasificacion['departamento'])
    publicacion.full_clean(exclude=['titulo_busqueda', 'contenido_busqueda'],
                           validate_unique=False, validate_constraints=False)
    return publicacion, clasificacion


def validar_entrada_persistencia(entrada):
    """Reutiliza validación y reglas H3.1 sin guardar, emitir señales ni usar IA.

    No consulta unicidad ni crea relaciones: la transacción de persistencia
    sigue siendo la autoridad para resolver identidades y carreras.
    """
    _, datos, _, seccion = _preparar(entrada)
    _clasificar_y_validar(datos, seccion)


def _guardar(fuente, datos, aliases, seccion, registro):
    # Cada reintento revierte publicación, alias, etiquetas y categorías juntos.
    for intento in range(3):
        try:
            with transaction.atomic():
                _bloquear_fuente(fuente)
                existente = _existente(fuente, datos, aliases)
                if existente is not None:
                    _vincular_aliases(fuente, aliases, existente)
                    return existente, False
                publicacion, clasificacion = _clasificar_y_validar(datos, seccion)
                publicacion.id_registro = registro
                publicacion.save(force_insert=True)  # Señales existentes generan etiquetas.
                _vincular_aliases(fuente, aliases, publicacion.pk)
                if clasificacion.get('confirmada') is True:
                    vincular_categoria_por_nombre(publicacion, clasificacion['categoria'])
                # Cola durable sólo para altas nuevas; comparte commit/rollback con H3.1.
                ProcesamientoIAMultifuente.objects.create(publicacion=publicacion)
                return publicacion.pk, True
        except DatabaseError as exc:
            codigo = getattr(exc.__cause__, 'sqlstate', None) or getattr(exc.__cause__, 'pgcode', None)
            if intento == 2 or not (isinstance(exc, IntegrityError) or codigo in ('40001', '40P01')):
                raise


def persistir_lote(entradas, *, dry_run=False):
    """Transacciones por noticia; dry-run simula alias sin escrituras ni bloqueos.

    Alias persistidos también en duplicados. Los conflictos históricos se
    informan por entrada, nunca se fusionan publicaciones automáticamente.
    """
    if type(dry_run) is not bool:
        raise ValueError('dry_run debe ser booleano.')
    registro = None
    if not dry_run:
        registro = RegistroDatos.objects.create(
            fuentes_api='RSS multifuente', fecha_ejecucion=timezone.now(),
            estado='EN_PROCESO', lenguaje='es')
    resultado = dict(dry_run=dry_run, registro_id=registro.pk if registro else None,
                     capturados=0, previstos=0, omitidas=0, errores=[], noticias=[])
    virtuales = {}
    for indice, entrada in enumerate(entradas):
        try:
            fuente, datos, aliases, seccion = _preparar(entrada)
            if dry_run:
                claves = {(fuente.identificador, url) for url in aliases}
                existente = _existente(fuente, datos, aliases)
                destinos = {virtuales[c] for c in claves if c in virtuales}
                if existente is not None:
                    destinos.add(existente)
                if len(destinos) > 1:
                    raise ConflictoIdentidad('Alias asociados a varias publicaciones.')
                if destinos:
                    destino = next(iter(destinos))
                    resultado['omitidas'] += 1
                    detalle = dict(indice=indice, estado='DUPLICADA',
                                   publicacion_id=destino if isinstance(destino, int) else None)
                else:
                    _, clasificacion = _clasificar_y_validar(datos, seccion)
                    destino = (fuente.identificador, datos['hash_origen'])
                    detalle = dict(indice=indice, estado='PREVISTA', hash_origen=datos['hash_origen'],
                                   categoria=clasificacion['categoria'] if clasificacion.get('confirmada') is True else None,
                                   etiquetas=sugerir_etiquetas(datos['titulo'], datos['contenido']))
                    resultado['previstos'] += 1
                virtuales.update(dict.fromkeys(claves, destino))
            else:
                pk, creada = _guardar(fuente, datos, aliases, seccion, registro)
                resultado['capturados' if creada else 'omitidas'] += 1
                detalle = dict(indice=indice, estado='GUARDADA' if creada else 'DUPLICADA', publicacion_id=pk)
                if creada:
                    detalle['hash_origen'] = datos['hash_origen']
            resultado['noticias'].append(detalle)
        except Exception as exc:
            codigo = ('conflicto_identidad' if isinstance(exc, ConflictoIdentidad) else
                      'datos_invalidos' if isinstance(exc, (ValueError, ValidationError, TypeError))
                      else 'persistencia_fallida')
            resultado['errores'].append(dict(indice=indice, codigo=codigo, tipo=type(exc).__name__))
    resultado['estado'] = ('PARCIAL' if resultado['capturados'] or resultado['previstos'] or resultado['omitidas']
                           else 'FALLO') if resultado['errores'] else 'EXITO'
    if registro:
        registro.estado = 'EXITO' if not resultado['errores'] else 'ERROR: ' + resultado['estado']
        registro.save(update_fields=['estado'])
    return resultado
