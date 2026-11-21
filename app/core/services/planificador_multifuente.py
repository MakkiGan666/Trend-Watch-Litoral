"""Planificación durable de ingesta reciente, sin worker automático al iniciar Django."""
from datetime import datetime, timedelta, timezone as dt_timezone
from email.utils import parsedate_to_datetime
import json
import math
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.models import (
    CacheRobotsMultifuente,
    ControlServicioIngestaMultifuente,
    ControlSolicitudRSSMetadatos,
    ProgramacionIngestaMultifuente,
    RegistroDatos,
    TrabajoIngestaMultifuente,
)
from core.services import descarga_segura, fuentes_rss, lector_rss, orquestador_multifuente
from core.services.persistencia_rss_metadatos import (
    FuenteBloqueada,
    FuenteRSSEnEspera,
    _politica_fuente,
    _finalizar_solicitud,
    _reservar_solicitud,
)

MAX_SNAPSHOT_BYTES = 128 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
ROBOTS_TTL = timedelta(hours=12)
ROBOTS_TTL_MAX = timedelta(hours=24)
ROBOTS_TTL_MARGEN = timedelta(minutes=5)
LEASE_SECONDS = 120
WORKER_LEASE_SECONDS = 300
MAX_RETRY_SECONDS = 3600
MAX_SNAPSHOT_ENTRIES = 30
MAX_METADATA_ITEMS_PER_CYCLE = 5
USER_AGENT = 'TrendWatch/1.0'
ACTIVE_STATES = (
    TrabajoIngestaMultifuente.Estado.SNAPSHOT_PENDIENTE,
    TrabajoIngestaMultifuente.Estado.PROCESANDO,
    TrabajoIngestaMultifuente.Estado.ESPERA,
    TrabajoIngestaMultifuente.Estado.REVISION_MANUAL,
)


class ReglasRobotsDeniegan(ValueError):
    pass


class LeasePerdido(RuntimeError):
    pass


def _catalogo():
    return {f.identificador: f for f in fuentes_rss.FUENTES_RSS}


def _fuente(fuente_id, *, exigir_habilitada=True, permitir_solo_metadatos=False):
    fuente = _catalogo().get(fuente_id)
    if fuente is None:
        raise ValueError('Fuente desconocida para ingesta multifuente.')
    if type(permitir_solo_metadatos) is not bool:
        raise ValueError('El permiso metadata-only debe ser booleano.')
    if exigir_habilitada and not fuente.habilitada and not permitir_solo_metadatos:
        raise ValueError('La fuente permanece deshabilitada en el catálogo.')
    return fuente


def _validar_politica_metadata(fuente):
    """Revalida los gates RSS y los límites H5.6 antes de consumir un feed."""
    try:
        return _politica_fuente(fuente)
    except (ImproperlyConfigured, ValueError) as exc:
        raise ValueError(f'Política RSS metadata-only incompleta: {exc}') from exc


@transaction.atomic
def configurar_fuente(fuente_id, *, intervalo_segundos=None, frecuencia_segundos=None,
                      intervalo_http_segundos=None, solo_metadatos=None):
    """Programa sin habilitar; admite la interfaz antigua y valores independientes."""
    fuente = _fuente(fuente_id, exigir_habilitada=False)
    if intervalo_segundos is not None and (
        frecuencia_segundos is not None or intervalo_http_segundos is not None
    ):
        raise ValueError('No combines --intervalo-segundos con los parámetros separados.')
    if intervalo_segundos is None and frecuencia_segundos is None and intervalo_http_segundos is None:
        frecuencia_segundos = intervalo_http_segundos = 3600
    if intervalo_segundos is not None:
        # Compatibilidad: históricamente este valor gobernaba ambos intervalos.
        frecuencia_segundos = intervalo_http_segundos = intervalo_segundos
    for valor, nombre in (
        (frecuencia_segundos, 'La frecuencia RSS'),
        (intervalo_http_segundos, 'El intervalo HTTP'),
    ):
        if valor is not None and (type(valor) is not int or valor < 60):
            raise ValueError(f'{nombre} debe ser de al menos 60 segundos.')
    if solo_metadatos is not None and type(solo_metadatos) is not bool:
        raise ValueError('El modo de ingesta debe ser booleano.')
    plan, _ = ProgramacionIngestaMultifuente.objects.get_or_create(
        fuente_id=fuente.identificador,
        defaults={
            'frecuencia_segundos': frecuencia_segundos or 3600,
            'intervalo_segundos': intervalo_http_segundos or 3600,
        },
    )
    plan = ProgramacionIngestaMultifuente.objects.select_for_update().get(pk=plan.pk)
    frecuencia_nueva = (plan.frecuencia_segundos if frecuencia_segundos is None
                        else frecuencia_segundos)
    intervalo_nuevo = (plan.intervalo_segundos if intervalo_http_segundos is None
                       else intervalo_http_segundos)
    cambio = (frecuencia_nueva != plan.frecuencia_segundos
              or intervalo_nuevo != plan.intervalo_segundos)
    if solo_metadatos is not None and solo_metadatos != plan.solo_metadatos:
        if TrabajoIngestaMultifuente.objects.filter(
            fuente_id=fuente.identificador, estado__in=ACTIVE_STATES,
        ).exists():
            raise ValueError('No se puede cambiar el modo mientras haya un trabajo abierto.')
        plan.solo_metadatos = solo_metadatos
    plan.frecuencia_segundos = frecuencia_nueva
    plan.intervalo_segundos = intervalo_nuevo
    if cambio and plan.ultima_ejecucion:
        intervalos = getattr(settings, 'RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE', {})
        h56 = intervalos.get(fuente.identificador, 0) if isinstance(intervalos, dict) else 0
        minimo = plan.ultima_ejecucion + timedelta(
            seconds=max(plan.frecuencia_segundos, plan.intervalo_segundos, h56),
        )
        plan.proxima_ejecucion = max(plan.proxima_ejecucion or timezone.now(), minimo)
    # La creación/edición de frecuencia nunca habilita ni aprueba una fuente.
    campos = ['frecuencia_segundos', 'intervalo_segundos', 'actualizado']
    if solo_metadatos is not None:
        campos.append('solo_metadatos')
    if cambio and plan.ultima_ejecucion:
        campos.append('proxima_ejecucion')
    plan.save(update_fields=campos)
    return plan


def habilitar_fuente(fuente_id, *, confirmar_revision_acceso=False,
                     confirmar_aprobacion_operativa=False):
    fuente = _fuente(fuente_id, exigir_habilitada=False)
    if confirmar_revision_acceso is not True or confirmar_aprobacion_operativa is not True:
        raise ValueError('Para habilitar se requieren ambas confirmaciones explícitas.')
    plan = ProgramacionIngestaMultifuente.objects.filter(fuente_id=fuente.identificador).first()
    if plan is None:
        raise ValueError('Configurá primero el intervalo de esta fuente.')
    if not fuente.habilitada and not plan.solo_metadatos:
        raise ValueError(
            'La fuente está deshabilitada en el catálogo para extracción completa; configurá '
            'explícitamente solo_metadatos para habilitar únicamente su feed RSS.'
        )
    if plan.solo_metadatos:
        _validar_politica_metadata(fuente)
    plan.acceso_revisado = True
    plan.aprobacion_operativa = True
    plan.habilitada = True
    plan.proxima_ejecucion = timezone.now()
    plan.save(update_fields=(
        'acceso_revisado', 'aprobacion_operativa', 'habilitada',
        'proxima_ejecucion', 'actualizado',
    ))
    return plan


def deshabilitar_fuente(fuente_id):
    plan = ProgramacionIngestaMultifuente.objects.filter(fuente_id=fuente_id).first()
    if plan is None:
        raise ValueError('La fuente no tiene una programación configurada.')
    plan.habilitada = False
    plan.proxima_ejecucion = None
    plan.save(update_fields=['habilitada', 'proxima_ejecucion', 'actualizado'])
    return plan


def _snapshot_item(indice, noticia):
    if len(noticia.resumen.encode('utf-8')) > 4000:
        raise ValueError('Resumen RSS excede el límite del snapshot; no se truncó.')
    return {
        'indice': indice,
        'fuente': noticia.fuente,
        'fuente_id': noticia.fuente_id,
        'titulo': noticia.titulo,
        'url': noticia.url,
        'fecha': noticia.fecha.isoformat() if noticia.fecha else None,
        'resumen': noticia.resumen,
        'seccion': noticia.seccion,
        'imagen_principal': noticia.imagen_principal,
        'estado': 'PENDIENTE',
    }


def _snapshot_metadata_item(indice, noticia):
    """Snapshot privado de metadatos; no conserva resumen, imagen ni cuerpo."""
    return {
        'indice': indice, 'fuente': noticia.fuente,
        'fuente_id': noticia.fuente_id, 'titulo': noticia.titulo,
        'url': noticia.url,
        'fecha': noticia.fecha.isoformat() if noticia.fecha else None,
        'estado': 'PENDIENTE',
    }


def _guardar_snapshot(trabajo_id, token, fencing, fuente_id, feed):
    indices = feed.indices_noticias
    if len(indices) != len(feed.noticias):
        indices = tuple(range(len(feed.noticias)))
    ahora = timezone.now()
    with transaction.atomic():
        trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
        _verificar_fence(trabajo, token, fencing)
        if trabajo.snapshot_capturado is not None:
            raise ValueError('El snapshot ya fue fijado; no se reemplaza por otro feed.')
        snapshot_fn = _snapshot_metadata_item if trabajo.solo_metadatos else _snapshot_item
        snapshot = [snapshot_fn(i, n) for i, n in zip(indices, feed.noticias)]
        payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(payload) > MAX_SNAPSHOT_BYTES:
            raise ValueError('Snapshot RSS excede 128 KiB; no se truncó ni se procesó parcialmente.')
        if trabajo.solo_metadatos:
            trabajo.registro = RegistroDatos.objects.create(
                fuentes_api=fuente_id, fecha_ejecucion=ahora,
                estado='EN_PROGRESO', lenguaje='RSS metadata-only',
            )
        resultados = [
            {'indice': i, 'estado': 'RECHAZADA', 'codigo': 'rss_entrada_invalida'}
            for i, _ in feed.rechazos
        ]
        trabajo.snapshot = snapshot
        trabajo.snapshot_capturado = ahora
        trabajo.url_feed_reanudacion = ''
        trabajo.entradas_feed = feed.total_entradas
        trabajo.entradas_snapshot = len(snapshot)
        trabajo.entradas_fuera_limite = feed.truncadas
        trabajo.rechazadas = len(feed.rechazos)
        trabajo.resultados = resultados
        trabajo.cursor = len(feed.rechazos)
        trabajo.estado = (TrabajoIngestaMultifuente.Estado.ESPERA
                          if snapshot else TrabajoIngestaMultifuente.Estado.COMPLETADO)
        if not snapshot:
            trabajo.snapshot = []
            trabajo.finalizado = ahora
            if trabajo.registro_id:
                trabajo.registro.estado = 'COMPLETADO'
                trabajo.registro.save(update_fields=['estado'])
        trabajo.save()
    if not snapshot:
        _programar_siguiente(fuente_id, ahora)


def _noticia_desde_snapshot(item):
    from datetime import datetime
    fecha = datetime.fromisoformat(item['fecha']) if item.get('fecha') else None
    return lector_rss.NoticiaRSS(
        fuente=item['fuente'], fuente_id=item['fuente_id'], titulo=item['titulo'],
        url=item['url'], fecha=fecha, resumen=item.get('resumen', ''),
        contenido_completo='', seccion=item.get('seccion', ''),
        imagen_principal=item.get('imagen_principal', ''),
    )


def _noticia_desde_snapshot_metadata(item):
    noticia = _noticia_desde_snapshot(item)
    return lector_rss.NoticiaRSS(
        fuente=noticia.fuente, fuente_id=noticia.fuente_id,
        titulo=noticia.titulo, url=noticia.url, fecha=noticia.fecha,
        resumen='', contenido_completo='', seccion='', imagen_principal='',
    )


def _verificar_fence(trabajo, token, fencing):
    if trabajo.token_arrendamiento != token or trabajo.fencing_token != fencing:
        raise LeasePerdido('El ejecutor perdió su lease; no puede confirmar checkpoints.')


def _programar_siguiente(fuente_id, ahora=None):
    ahora = ahora or timezone.now()
    plan = ProgramacionIngestaMultifuente.objects.get(fuente_id=fuente_id)
    intervalos = getattr(settings, 'RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE', {})
    h56 = intervalos.get(fuente_id, 0) if isinstance(intervalos, dict) else 0
    if type(h56) is not int or h56 < 0:
        raise ValueError('El intervalo H5.6 configurado es inválido.')
    ProgramacionIngestaMultifuente.objects.filter(fuente_id=fuente_id).update(
        ultima_ejecucion=ahora,
        proxima_ejecucion=ahora + timedelta(
            seconds=max(plan.frecuencia_segundos, plan.intervalo_segundos, h56),
        ),
    )


def _reservar_trabajo(plan, ahora):
    try:
        with transaction.atomic():
            plan = ProgramacionIngestaMultifuente.objects.select_for_update().get(pk=plan.pk)
            if not (plan.habilitada and plan.acceso_revisado and plan.aprobacion_operativa):
                return None
            fuente = _fuente(
                plan.fuente_id, exigir_habilitada=True,
                permitir_solo_metadatos=plan.solo_metadatos,
            )
            del fuente
            trabajo = (TrabajoIngestaMultifuente.objects.select_for_update()
                       .filter(fuente_id=plan.fuente_id, estado__in=ACTIVE_STATES)
                       .first())
            if trabajo is not None and trabajo.solo_metadatos != plan.solo_metadatos:
                return None
            if trabajo is None:
                if plan.proxima_ejecucion and plan.proxima_ejecucion > ahora:
                    return None
                trabajo = TrabajoIngestaMultifuente.objects.create(
                    fuente_id=plan.fuente_id,
                    solo_metadatos=plan.solo_metadatos,
                    estado=TrabajoIngestaMultifuente.Estado.SNAPSHOT_PENDIENTE,
                )
            if trabajo.estado in (
                TrabajoIngestaMultifuente.Estado.REVISION_MANUAL,
                TrabajoIngestaMultifuente.Estado.FALLIDO,
                TrabajoIngestaMultifuente.Estado.CANCELADO,
            ):
                return None
            if trabajo.proxima_accion and trabajo.proxima_accion > ahora:
                return None
            if trabajo.arrendamiento_hasta and trabajo.arrendamiento_hasta > ahora:
                return None
            token = uuid4()
            trabajo.fencing_token += 1
            trabajo.token_arrendamiento = token
            trabajo.arrendamiento_hasta = ahora + timedelta(seconds=LEASE_SECONDS)
            trabajo.estado = (TrabajoIngestaMultifuente.Estado.SNAPSHOT_PENDIENTE
                              if trabajo.snapshot_capturado is None else
                              TrabajoIngestaMultifuente.Estado.PROCESANDO)
            trabajo.save(update_fields=(
                'fencing_token', 'token_arrendamiento', 'arrendamiento_hasta', 'estado', 'actualizado',
            ))
            return trabajo.pk, token, trabajo.fencing_token
    except IntegrityError:
        # Otra ejecución ganó la restricción única de trabajo abierto.
        return None


def _control_h5(fuente_id):
    return ControlSolicitudRSSMetadatos.objects.filter(fuente_id=fuente_id).first()


def _proxima_por_control(fuente_id, segundos_minimos):
    control = _control_h5(fuente_id)
    ahora = timezone.now()
    if control is None:
        return ahora + timedelta(seconds=segundos_minimos)
    if control.estado == ControlSolicitudRSSMetadatos.Estado.ESPERA:
        return max(ahora, control.retry_after_hasta or ahora)
    if control.estado in (ControlSolicitudRSSMetadatos.Estado.EN_CURSO,
                          ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL):
        return None
    return max(ahora, (control.ultimo_intento or ahora) + timedelta(seconds=segundos_minimos))


def _backoff(trabajo):
    return min(MAX_RETRY_SECONDS, 60 * (2 ** min(trabajo.errores, 5)))


class ControlHTTPConRobots:
    """Reserva H5.6 y robots antes de cada GET, incluyendo cada salto HTTP."""
    def __init__(self, fuente, intervalo_base):
        self.fuente = fuente
        self.intervalo_base = intervalo_base
        self._cargando = set()
        self._intervalo_actual = intervalo_base
        self._fallback_429 = getattr(settings, 'RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS', 86400)

    @staticmethod
    def _es_robots(url):
        partes = urlsplit(url)
        return (partes.path or '/') == '/robots.txt'

    def _parser(self, host):
        ahora = timezone.now()
        cache = CacheRobotsMultifuente.objects.filter(
            fuente_id=self.fuente.identificador, host=host, expira__gt=ahora,
        ).first()
        if cache and cache.expira > cache.consultado + ROBOTS_TTL_MAX:
            cache = None
        if cache is None:
            if timedelta(seconds=self.intervalo_base) + ROBOTS_TTL_MARGEN > ROBOTS_TTL_MAX:
                raise ValueError(
                    'El intervalo HTTP supera la vigencia máxima segura de robots.txt; '
                    'se requiere revisión manual.'
                )
            robots_url = f'https://{host}/robots.txt'
            self._cargando.add(host)
            metadatos_http = {}
            try:
                texto = descarga_segura.descargar(
                    robots_url, fuente=self.fuente, control_solicitud=self,
                    observador_respuesta=metadatos_http.update,
                ).decode('utf-8', errors='replace')
            finally:
                self._cargando.discard(host)
            if len(texto.encode('utf-8')) > MAX_ROBOTS_BYTES:
                raise ValueError('robots.txt excede 256 KiB; política no cacheada y fuente detenida.')
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(texto.splitlines())
            intervalo_reglas = self._intervalo_reglas(parser)
            if timedelta(seconds=intervalo_reglas) + ROBOTS_TTL_MARGEN > ROBOTS_TTL_MAX:
                raise ValueError(
                    'Las restricciones de robots.txt exceden la vigencia máxima segura '
                    'de caché; se requiere revisión manual.'
                )
            ttl = self._ttl_cache_robots(intervalo_reglas, metadatos_http)
            CacheRobotsMultifuente.objects.update_or_create(
                fuente_id=self.fuente.identificador, host=host,
                defaults={'reglas': texto, 'consultado': ahora, 'expira': ahora + ttl},
            )
            reglas = texto
        else:
            reglas = cache.reglas
        parser = RobotFileParser()
        parser.set_url(f'https://{host}/robots.txt')
        parser.parse(reglas.splitlines())
        return parser

    def _ttl_cache_robots(self, intervalo_requerido, metadatos_http):
        cache_control = metadatos_http.get('cache-control') or ''
        directivas = {}
        banderas = set()
        for parte in cache_control.split(','):
            nombre, separador, valor = parte.strip().partition('=')
            nombre = nombre.lower()
            if separador:
                directivas[nombre] = valor.strip().strip('"')
            elif nombre:
                banderas.add(nombre)
        requerido = timedelta(seconds=intervalo_requerido) + ROBOTS_TTL_MARGEN
        if {'no-cache', 'no-store', 'private'} & (banderas | directivas.keys()):
            raise ValueError(
                'Cache-Control impide reutilizar robots.txt; se requiere revisión manual.'
            )
        directiva_edad = directivas.get('s-maxage', directivas.get('max-age'))
        if directiva_edad is not None:
            if not directiva_edad.isascii() or not directiva_edad.isdecimal():
                raise ValueError('Cache-Control max-age inválido; se requiere revisión manual.')
            edad = metadatos_http.get('age') or '0'
            if not edad.isascii() or not edad.isdecimal():
                raise ValueError('Age de robots.txt inválido; se requiere revisión manual.')
            restante = max(0, int(directiva_edad) - int(edad))
            ttl = timedelta(seconds=min(restante, int(ROBOTS_TTL_MAX.total_seconds())))
        elif metadatos_http.get('expires'):
            try:
                expira = parsedate_to_datetime(metadatos_http['expires'])
                fecha = parsedate_to_datetime(metadatos_http['date']) if metadatos_http.get('date') else timezone.now()
                if expira.tzinfo is None or fecha.tzinfo is None:
                    raise ValueError
                edad = metadatos_http.get('age') or '0'
                if not edad.isascii() or not edad.isdecimal():
                    raise ValueError
                ttl = expira - fecha - timedelta(seconds=int(edad))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError('Expires de robots.txt inválido; se requiere revisión manual.') from exc
        else:
            ttl = max(ROBOTS_TTL, requerido)
        ttl = min(ttl, ROBOTS_TTL_MAX)
        if ttl < requerido:
            raise ValueError(
                'La vigencia HTTP de robots.txt no cubre el intervalo requerido; '
                'se requiere revisión manual.'
            )
        return ttl

    def _intervalo_reglas(self, parser):
        retrasos = [self.intervalo_base]
        for agente in ('TrendWatch', USER_AGENT, '*'):
            demora = parser.crawl_delay(agente)
            if demora is not None:
                retrasos.append(int(demora))
            tasa = parser.request_rate(agente)
            if tasa and tasa.requests:
                retrasos.append(math.ceil(tasa.seconds / tasa.requests))
        return max(retrasos)

    @staticmethod
    def _ventanas_visit_time(reglas):
        """Devuelve ventanas UTC aplicables; una directiva malformada falla cerrado."""
        grupos = []
        actual = None
        for linea in reglas.splitlines():
            linea = linea.split('#', 1)[0].strip()
            if not linea or ':' not in linea:
                continue
            clave, valor = (parte.strip() for parte in linea.split(':', 1))
            clave = clave.lower()
            if clave == 'user-agent':
                if actual is None or actual['directivas']:
                    actual = {'agentes': [], 'directivas': []}
                    grupos.append(actual)
                actual['agentes'].append(valor.lower())
            elif actual is not None:
                actual['directivas'].append((clave, valor))
        prioridad = -1
        valores = []
        for grupo in grupos:
            ids = grupo['agentes']
            puntuacion = 2 if any(a in ('trendwatch/1.0', 'trendwatch') for a in ids) else (
                1 if '*' in ids else -1
            )
            if puntuacion > prioridad:
                prioridad, valores = puntuacion, []
            if puntuacion == prioridad:
                valores.extend(v for k, v in grupo['directivas'] if k == 'visit-time')
        ventanas = []
        for valor in valores:
            if not valor.isascii() or len(valor) != 9 or valor[4] != '-':
                raise ValueError('Visit-time de robots.txt inválido; acceso detenido.')
            inicio, fin = valor[:4], valor[5:]
            if (not inicio.isdecimal() or not fin.isdecimal()
                    or int(inicio[:2]) > 23 or int(inicio[2:]) > 59
                    or int(fin[:2]) > 24 or int(fin[2:]) > 59
                    or (fin[:2] == '24' and fin[2:] != '00')):
                raise ValueError('Visit-time de robots.txt inválido; acceso detenido.')
            ventanas.append((int(inicio[:2]) * 60 + int(inicio[2:]),
                             int(fin[:2]) * 60 + int(fin[2:])))
        return ventanas

    def _espera_visit_time(self, reglas, ahora=None):
        ventanas = self._ventanas_visit_time(reglas)
        if not ventanas:
            return None
        ahora = ahora or timezone.now()
        utc = ahora.astimezone(dt_timezone.utc)

        def permitido(m):
            return all((inicio <= m < fin) if inicio < fin else (m >= inicio or m < fin)
                       for inicio, fin in ventanas)

        minuto = utc.hour * 60 + utc.minute
        if permitido(minuto):
            return None
        base = utc.replace(second=0, microsecond=0)
        for delta in range(1, 2881):
            candidato = base + timedelta(minutes=delta)
            if permitido(candidato.hour * 60 + candidato.minute):
                return candidato.astimezone(ahora.tzinfo)
        raise ValueError('Visit-time no contiene una ventana alcanzable; acceso detenido.')

    def antes(self, url):
        partes = self.fuente.validar_url(url)
        host = partes.hostname
        robots = self._es_robots(url)
        intervalo = self.intervalo_base
        if not robots and host not in self._cargando:
            parser = self._parser(host)
            if not parser.can_fetch(USER_AGENT, url):
                raise ReglasRobotsDeniegan('robots.txt no permite esta ruta; no se hizo GET.')
            reglas_cache = CacheRobotsMultifuente.objects.get(
                fuente_id=self.fuente.identificador, host=host,
            ).reglas
            espera_visit = self._espera_visit_time(reglas_cache)
            if espera_visit is not None:
                raise FuenteRSSEnEspera(max(1, math.ceil(
                    (espera_visit - timezone.now()).total_seconds(),
                )))
            intervalo = self._intervalo_reglas(parser)
        reserva = _reservar_solicitud(self.fuente, intervalo)
        self._intervalo_actual = intervalo
        return {'control_id': reserva, 'intervalo': intervalo, 'robots': robots}

    def respuesta(self, reserva, url, status, retry_after_header):
        retry = None
        revision_manual = status in (401, 403) or (reserva['robots'] and status != 200 and status != 429)
        if status == 429:
            retry, excesivo = descarga_segura._interpretar_retry_after(retry_after_header)
            if retry is None and not excesivo:
                retry = self._fallback_429
            revision_manual = excesivo
        estado, hasta = _finalizar_solicitud(
            self.fuente, reserva['control_id'], reserva['intervalo'],
            retry_after_segundos=retry, revision_manual=revision_manual,
        )
        return {
            'revision_manual': estado == ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL,
            'espera_hasta': hasta if status in (301, 302, 303, 307, 308) else None,
        }

    def error(self, reserva, url, exc):
        # Los errores DNS/conexión/read consumen intervalo aunque no haya status HTTP.
        _finalizar_solicitud(self.fuente, reserva['control_id'], reserva['intervalo'])


def _serializar_estado(resultado, fuente_id):
    fuente_resultado = next((x for x in resultado.get('fuentes', []) if x['fuente'] == fuente_id), {})
    return fuente_resultado


def _marcar_espera(trabajo_id, token, fencing, *, codigo, hasta=None):
    with transaction.atomic():
        trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
        _verificar_fence(trabajo, token, fencing)
        trabajo.estado = TrabajoIngestaMultifuente.Estado.ESPERA
        trabajo.proxima_accion = hasta or timezone.now() + timedelta(seconds=_backoff(trabajo))
        trabajo.errores += 1
        trabajo.codigo_error = codigo[:64]
        trabajo.token_arrendamiento = None
        trabajo.arrendamiento_hasta = None
        trabajo.save()


def _espera_fecha(detalle):
    valor = detalle.get('espera_hasta')
    if not valor:
        return None
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return None
    return fecha if timezone.is_aware(fecha) else None


def _marcar_espera_continuacion(trabajo_id, token, fencing, *, codigo, hasta,
                                url_feed=None, indice_articulo=None, url_articulo=None):
    for url in (url_feed, url_articulo):
        if url and len(url) > 2048:
            raise ValueError('La URL de reanudación excede 2048 caracteres.')
    with transaction.atomic():
        trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
        _verificar_fence(trabajo, token, fencing)
        if url_feed:
            trabajo.url_feed_reanudacion = url_feed
        if url_articulo and indice_articulo is not None:
            for item in trabajo.snapshot:
                if item['indice'] == indice_articulo:
                    item['url_reanudacion'] = url_articulo
                    break
            serializado = json.dumps(trabajo.snapshot, ensure_ascii=False, separators=(',', ':'))
            if len(serializado.encode('utf-8')) > MAX_SNAPSHOT_BYTES:
                raise ValueError('El checkpoint con redirección excede 128 KiB; requiere revisión manual.')
        trabajo.estado = TrabajoIngestaMultifuente.Estado.ESPERA
        trabajo.proxima_accion = hasta or timezone.now() + timedelta(seconds=_backoff(trabajo))
        trabajo.errores += 1
        trabajo.codigo_error = codigo[:64]
        trabajo.token_arrendamiento = None
        trabajo.arrendamiento_hasta = None
        trabajo.save()


def _marcar_revision(trabajo_id, token, fencing, codigo):
    with transaction.atomic():
        trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
        _verificar_fence(trabajo, token, fencing)
        trabajo.estado = TrabajoIngestaMultifuente.Estado.REVISION_MANUAL
        trabajo.proxima_accion = None
        trabajo.codigo_error = codigo[:64]
        trabajo.errores += 1
        trabajo.token_arrendamiento = None
        trabajo.arrendamiento_hasta = None
        trabajo.save()


def _completar(trabajo_id, token, fencing):
    ahora = timezone.now()
    fuente_id = None
    with transaction.atomic():
        trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
        _verificar_fence(trabajo, token, fencing)
        fuente_id = trabajo.fuente_id
        trabajo.estado = TrabajoIngestaMultifuente.Estado.COMPLETADO
        trabajo.snapshot = []
        trabajo.proxima_accion = None
        trabajo.finalizado = ahora
        trabajo.token_arrendamiento = None
        trabajo.arrendamiento_hasta = None
        trabajo.save()
    _programar_siguiente(fuente_id, ahora)


def _guardar_resultado_item(trabajo_id, token, fencing, *, indice, estado, publicacion_id=None, codigo=''):
    ahora = timezone.now()
    trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
    _verificar_fence(trabajo, token, fencing)
    resultados = list(trabajo.resultados)
    resultados.append({'indice': indice, 'estado': estado,
                       'publicacion_id': publicacion_id, 'codigo': codigo[:64]})
    items = list(trabajo.snapshot)
    for item in items:
        if item['indice'] == indice:
            item['estado'] = estado
            break
    trabajo.resultados = resultados
    trabajo.snapshot = items
    trabajo.cursor += 1
    trabajo.procesadas += 1
    if estado == 'PERSISTIDA':
        trabajo.nuevas += 1
    elif estado == 'DUPLICADA':
        trabajo.duplicadas += 1
    else:
        trabajo.rechazadas += 1
    pendientes = [x for x in items if x['estado'] == 'PENDIENTE']
    if pendientes:
        siguiente = _proxima_por_control(trabajo.fuente_id, 60)
        trabajo.estado = TrabajoIngestaMultifuente.Estado.ESPERA
        trabajo.proxima_accion = siguiente or ahora + timedelta(seconds=MAX_RETRY_SECONDS)
    else:
        trabajo.estado = TrabajoIngestaMultifuente.Estado.COMPLETADO
        trabajo.snapshot = []
        trabajo.proxima_accion = None
        trabajo.finalizado = ahora
    fuente_id = trabajo.fuente_id
    trabajo.token_arrendamiento = None
    trabajo.arrendamiento_hasta = None
    trabajo.save()
    return not pendientes, fuente_id


def _resultado_transitorio(detalle):
    status = detalle.get('http_status')
    codigo = detalle.get('codigo', '')
    if status in (401, 403) or codigo in ('ReglasRobotsDeniegan', 'FuenteBloqueada'):
        return 'revision'
    if status == 429 or codigo in ('FuenteRSSEnEspera', 'DescargaPausada'):
        return 'espera'
    if status is not None and status >= 500:
        return 'espera'
    if codigo in ('TimeoutError', 'ConnectionError', 'gaierror', 'OSError', 'DatabaseError'):
        return 'espera'
    return 'rechazo'


def _procesar_snapshot_metadata(trabajo_id, token, fencing, fuente):
    """Persiste hasta cinco fichas y sus checkpoints en transacciones atómicas."""
    from core.services.persistencia_rss_metadatos import (
        _codigo_rechazo, _fuente_canonica, _persistir_item, _validar_item,
    )

    fuente_persistencia = _fuente_canonica(fuente.identificador)
    limite_configurado, _, _ = _validar_politica_metadata(fuente)
    persistidas = duplicadas = rechazadas = 0
    indices = []
    finalizado = False
    for _ in range(min(MAX_METADATA_ITEMS_PER_CYCLE, limite_configurado)):
        with transaction.atomic():
            trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
            _verificar_fence(trabajo, token, fencing)
            item = next((x for x in trabajo.snapshot if x['estado'] == 'PENDIENTE'), None)
            if item is None:
                finalizado = True
                break
            noticia = _noticia_desde_snapshot_metadata(item)
            codigo = ''
            publicacion_id = None
            try:
                campos = _validar_item(noticia, fuente_persistencia)
            except (TypeError, ValueError) as exc:
                estado, codigo = 'RECHAZADA', _codigo_rechazo(exc)
            else:
                publicacion_id, creada = _persistir_item(
                    fuente_persistencia, noticia, campos, trabajo.registro,
                )
                estado = 'PERSISTIDA' if creada else 'DUPLICADA'
            # La escritura de la publicación arriba y este avance de snapshot
            # comparten la transacción exterior: jamás se adelanta el cursor.
            item['estado'] = estado
            resultados = list(trabajo.resultados)
            resultados.append({
                'indice': item['indice'], 'estado': estado,
                'publicacion_id': publicacion_id, 'codigo': codigo,
            })
            trabajo.resultados = resultados
            trabajo.procesadas += 1
            trabajo.cursor += 1
            if estado == 'PERSISTIDA':
                trabajo.nuevas += 1
                persistidas += 1
            elif estado == 'DUPLICADA':
                trabajo.duplicadas += 1
                duplicadas += 1
            else:
                trabajo.rechazadas += 1
                rechazadas += 1
            indices.append(item['indice'])
            pendientes = any(x['estado'] == 'PENDIENTE' for x in trabajo.snapshot)
            if pendientes:
                trabajo.estado = TrabajoIngestaMultifuente.Estado.ESPERA
                trabajo.proxima_accion = timezone.now() + timedelta(seconds=15)
            else:
                trabajo.estado = TrabajoIngestaMultifuente.Estado.COMPLETADO
                trabajo.snapshot = []
                trabajo.proxima_accion = None
                trabajo.finalizado = timezone.now()
                trabajo.token_arrendamiento = None
                trabajo.arrendamiento_hasta = None
                finalizado = True
                if trabajo.registro_id:
                    trabajo.registro.estado = 'COMPLETADO'
                    trabajo.registro.save(update_fields=['estado'])
            trabajo.save()
            if not pendientes:
                break
    if finalizado:
        _programar_siguiente(fuente.identificador, timezone.now())
        estado_final = 'COMPLETADO'
    else:
        with transaction.atomic():
            trabajo = TrabajoIngestaMultifuente.objects.select_for_update().get(pk=trabajo_id)
            _verificar_fence(trabajo, token, fencing)
            trabajo.estado = TrabajoIngestaMultifuente.Estado.ESPERA
            trabajo.proxima_accion = timezone.now() + timedelta(seconds=15)
            trabajo.token_arrendamiento = None
            trabajo.arrendamiento_hasta = None
            trabajo.save(update_fields=(
                'estado', 'proxima_accion', 'token_arrendamiento',
                'arrendamiento_hasta', 'actualizado',
            ))
        estado_final = 'ESPERA'
    return {
        'fuente': fuente.identificador, 'estado': estado_final,
        'procesadas': len(indices), 'nuevas': persistidas,
        'duplicadas': duplicadas, 'rechazadas': rechazadas,
        'indices': indices,
    }


def _procesar_unidad(trabajo_id, token, fencing, config):
    trabajo = TrabajoIngestaMultifuente.objects.get(pk=trabajo_id)
    if trabajo.solo_metadatos != config.solo_metadatos:
        raise ValueError('El modo del trabajo no coincide con su programación congelada.')
    fuente = _fuente(
        trabajo.fuente_id, exigir_habilitada=True,
        permitir_solo_metadatos=trabajo.solo_metadatos,
    )
    if trabajo.solo_metadatos:
        _validar_politica_metadata(fuente)
    intervalos_h56 = getattr(settings, 'RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE', {})
    if not isinstance(intervalos_h56, dict):
        raise ValueError('La configuración H5.6 de intervalos debe ser un mapa.')
    h56 = intervalos_h56.get(fuente.identificador, 0)
    if type(h56) is not int or h56 < 0:
        raise ValueError('El intervalo H5.6 configurado es inválido.')
    intervalo_efectivo = max(config.intervalo_segundos, h56)
    control_http = ControlHTTPConRobots(fuente, intervalo_efectivo)
    if trabajo.snapshot_capturado is None:
        guardar = lambda fuente_id, feed: _guardar_snapshot(
            trabajo_id, token, fencing, fuente_id, feed,
        )
        try:
            resultado = orquestador_multifuente.ejecutar_ingesta_multifuente(
                [fuente.identificador], limite_por_fuente=MAX_SNAPSHOT_ENTRIES,
                limite_total=MAX_SNAPSHOT_ENTRIES, dry_run=False, procesar_ia=False,
                solo_snapshot=True, guardar_snapshot=guardar,
                control_solicitud=control_http,
                solo_metadatos=trabajo.solo_metadatos,
                feed_urls={fuente.identificador: trabajo.url_feed_reanudacion}
                if trabajo.url_feed_reanudacion else None,
            )
        except Exception as exc:
            _marcar_revision(trabajo_id, token, fencing, type(exc).__name__)
            return {'fuente': fuente.identificador, 'estado': 'REVISION_MANUAL', 'error': type(exc).__name__}
        resumen = _serializar_estado(resultado, fuente.identificador)
        actual = TrabajoIngestaMultifuente.objects.get(pk=trabajo_id)
        if actual.snapshot_capturado is not None:
            if actual.estado == TrabajoIngestaMultifuente.Estado.COMPLETADO:
                _liberar_lease(trabajo_id, token, fencing)
                return {'fuente': fuente.identificador, 'estado': 'COMPLETADO', 'snapshot': 0}
            hasta = _proxima_por_control(fuente.identificador, intervalo_efectivo)
            _marcar_espera(trabajo_id, token, fencing, codigo='snapshot_capturado', hasta=hasta)
            return {'fuente': fuente.identificador, 'estado': 'SNAPSHOT_GUARDADO',
                    'entradas': actual.entradas_snapshot, 'fuera_limite': actual.entradas_fuera_limite}
        detalle = (resumen.get('errores') or [{}])[0]
        control = _control_h5(fuente.identificador)
        if control and control.estado in (
            ControlSolicitudRSSMetadatos.Estado.EN_CURSO,
            ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL,
        ):
            _marcar_revision(trabajo_id, token, fencing, detalle.get('codigo', 'control_h5_pendiente'))
            return {'fuente': fuente.identificador, 'estado': 'REVISION_MANUAL',
                    'error': detalle.get('codigo')}
        tipo = _resultado_transitorio(detalle)
        if tipo == 'revision':
            _marcar_revision(trabajo_id, token, fencing, detalle.get('codigo', 'revision_manual'))
            return {'fuente': fuente.identificador, 'estado': 'REVISION_MANUAL', 'error': detalle.get('codigo')}
        if tipo == 'espera':
            hasta = _espera_fecha(detalle) or _proxima_por_control(
                fuente.identificador, intervalo_efectivo,
            )
            _marcar_espera_continuacion(
                trabajo_id, token, fencing, codigo=detalle.get('codigo', 'espera'), hasta=hasta,
                url_feed=detalle.get('url_reanudacion'),
            )
            return {'fuente': fuente.identificador, 'estado': 'ESPERA', 'error': detalle.get('codigo')}
        _marcar_revision(trabajo_id, token, fencing, detalle.get('codigo', 'fallo_feed'))
        return {'fuente': fuente.identificador, 'estado': 'REVISION_MANUAL', 'error': detalle.get('codigo')}

    if trabajo.solo_metadatos:
        return _procesar_snapshot_metadata(trabajo_id, token, fencing, fuente)

    item = next((x for x in trabajo.snapshot if x['estado'] == 'PENDIENTE'), None)
    if item is None:
        _completar(trabajo_id, token, fencing)
        return {'fuente': fuente.identificador, 'estado': 'COMPLETADO'}
    noticia = _noticia_desde_snapshot(item)
    feed = lector_rss.ResultadoRSS(
        noticias=(noticia,), rechazos=(), total_entradas=1, truncadas=0,
        indices_noticias=(item['indice'],),
    )
    resultado = orquestador_multifuente.ejecutar_ingesta_multifuente(
        [fuente.identificador], limite_por_fuente=1, limite_total=1,
        dry_run=False, procesar_ia=False,
        snapshots={fuente.identificador: feed}, control_solicitud=control_http,
            omitir_conocidas=True,
        articulo_urls={fuente.identificador: item['url_reanudacion']}
        if item.get('url_reanudacion') else None,
    )
    resumen = _serializar_estado(resultado, fuente.identificador)
    if resumen.get('nuevas', 0):
        estado, publicacion_id, codigo = 'PERSISTIDA', None, ''
        detalles = resultado.get('fuentes', [{}])[0].get('noticias', [])
        if detalles:
            publicacion_id = detalles[-1].get('publicacion_id')
    elif resumen.get('duplicadas', 0):
        estado, publicacion_id, codigo = 'DUPLICADA', None, ''
        detalles = resultado.get('fuentes', [{}])[0].get('noticias', [])
        if detalles:
            publicacion_id = detalles[-1].get('publicacion_id')
    else:
        detalle = (resumen.get('errores') or [{}])[0]
        tipo = _resultado_transitorio(detalle)
        control = _control_h5(fuente.identificador)
        if tipo == 'revision' or (control and control.estado == ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL):
            _marcar_revision(trabajo_id, token, fencing, detalle.get('codigo', 'revision_manual'))
            return {'fuente': fuente.identificador, 'estado': 'REVISION_MANUAL', 'error': detalle.get('codigo')}
        if tipo == 'espera' or (control and control.estado == ControlSolicitudRSSMetadatos.Estado.ESPERA):
            hasta = _espera_fecha(detalle) or _proxima_por_control(
                fuente.identificador, intervalo_efectivo,
            )
            _marcar_espera_continuacion(
                trabajo_id, token, fencing, codigo=detalle.get('codigo', 'espera'), hasta=hasta,
                indice_articulo=item['indice'], url_articulo=detalle.get('url_reanudacion'),
            )
            return {'fuente': fuente.identificador, 'estado': 'ESPERA', 'error': detalle.get('codigo')}
        if resumen.get('persistencia_incierta'):
            _marcar_espera(trabajo_id, token, fencing, codigo='persistencia_incierta')
            return {'fuente': fuente.identificador, 'estado': 'ESPERA', 'error': 'persistencia_incierta'}
        estado, publicacion_id, codigo = 'RECHAZADA', None, detalle.get('codigo', 'datos_invalidos')
    with transaction.atomic():
        completo, fuente_id = _guardar_resultado_item(
            trabajo_id, token, fencing, indice=item['indice'], estado=estado,
            publicacion_id=publicacion_id, codigo=codigo,
        )
    if completo:
        _programar_siguiente(fuente_id)
    return {'fuente': fuente.identificador, 'estado': estado,
            'indice': item['indice'], 'publicacion_id': publicacion_id}


def _liberar_lease(trabajo_id, token, fencing):
    TrabajoIngestaMultifuente.objects.filter(
        pk=trabajo_id, token_arrendamiento=token, fencing_token=fencing,
    ).update(token_arrendamiento=None, arrendamiento_hasta=None)


def ejecutar_ciclo(*, max_fuentes=5):
    if type(max_fuentes) is not int or not 1 <= max_fuentes <= 5:
        raise ValueError('max_fuentes debe estar entre 1 y 5.')
    ahora = timezone.now()
    planes = list(ProgramacionIngestaMultifuente.objects.filter(
        habilitada=True, acceso_revisado=True, aprobacion_operativa=True,
    ).order_by('proxima_ejecucion', 'fuente_id'))
    resultados = []
    unidades_iniciadas = 0
    for plan in planes:
        if unidades_iniciadas >= max_fuentes:
            break
        try:
            fuente = _fuente(
                plan.fuente_id, exigir_habilitada=True,
                permitir_solo_metadatos=plan.solo_metadatos,
            )
            if plan.solo_metadatos:
                _validar_politica_metadata(fuente)
        except ValueError as exc:
            resultados.append({'fuente': plan.fuente_id, 'estado': 'OMITIDA', 'causa': str(exc)})
            continue
        trabajo_info = _reservar_trabajo(plan, ahora)
        if trabajo_info is None:
            continue
        unidades_iniciadas += 1
        trabajo_id, token, fencing = trabajo_info
        config = ProgramacionIngestaMultifuente.objects.get(pk=plan.pk)
        try:
            resultados.append(_procesar_unidad(trabajo_id, token, fencing, config))
        except LeasePerdido:
            resultados.append({'fuente': plan.fuente_id, 'estado': 'LEASE_PERDIDO'})
        except (DatabaseError, OSError, TimeoutError) as exc:
            try:
                _marcar_espera(trabajo_id, token, fencing, codigo=type(exc).__name__)
            except Exception:
                pass
            resultados.append({'fuente': plan.fuente_id, 'estado': 'ESPERA', 'error': type(exc).__name__})
        except Exception as exc:
            try:
                _marcar_revision(trabajo_id, token, fencing, type(exc).__name__)
            except Exception:
                pass
            resultados.append({'fuente': plan.fuente_id, 'estado': 'REVISION_MANUAL', 'error': type(exc).__name__})
    resultado = {'fuentes_consideradas': len(planes), 'resultados': resultados}
    if getattr(settings, 'DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA', False):
        try:
            from core.services.deteccion_incremental_multifuente import procesar_cola_incremental
            resultado['deteccion_editorial'] = procesar_cola_incremental()
        except Exception as exc:
            # Un fallo del consumidor de sombra no invalida los resultados de
            # ingesta de fuentes ya confirmados en este ciclo.
            resultado['deteccion_editorial'] = {'habilitada': True, 'error': type(exc).__name__}
    return resultado


def _heartbeat(token, fencing):
    ahora = timezone.now()
    return ControlServicioIngestaMultifuente.objects.filter(
        pk=1, activo=True, token_worker=token, fencing_token=fencing,
    ).update(heartbeat=ahora, worker_hasta=ahora + timedelta(seconds=WORKER_LEASE_SECONDS))


def iniciar_worker(*, intervalo_poll=15, max_fuentes=5, stop_event=None):
    if type(intervalo_poll) is not int or not 5 <= intervalo_poll <= 60:
        raise ValueError('El polling debe estar entre 5 y 60 segundos.')
    with transaction.atomic():
        control, _ = ControlServicioIngestaMultifuente.objects.select_for_update().get_or_create(pk=1)
        ahora = timezone.now()
        if (control.activo and control.worker_hasta and control.worker_hasta > ahora):
            raise ValueError('Ya hay un worker activo; no se inicia otro.')
        control.activo = True
        control.parada_solicitada = False
        control.fencing_token += 1
        token = uuid4()
        control.token_worker = token
        control.heartbeat = ahora
        control.worker_hasta = ahora + timedelta(seconds=WORKER_LEASE_SECONDS)
        control.save()
        fencing = control.fencing_token
    ciclos = 0
    try:
        while True:
            actual = ControlServicioIngestaMultifuente.objects.get(pk=1)
            if actual.token_worker != token or actual.fencing_token != fencing:
                raise LeasePerdido('Otro worker tomó el control; este se detiene.')
            if actual.parada_solicitada or (stop_event and stop_event.is_set()):
                break
            ejecutar_ciclo(max_fuentes=max_fuentes)
            ciclos += 1
            _heartbeat(token, fencing)
            for _ in range(intervalo_poll):
                actual.refresh_from_db()
                if actual.parada_solicitada or (stop_event and stop_event.is_set()):
                    break
                time.sleep(1)
    finally:
        ControlServicioIngestaMultifuente.objects.filter(
            pk=1, token_worker=token, fencing_token=fencing,
        ).update(activo=False, token_worker=None, worker_hasta=None, heartbeat=timezone.now())
    return {'ciclos_completados': ciclos}


def solicitar_detencion():
    control, _ = ControlServicioIngestaMultifuente.objects.get_or_create(pk=1)
    control.parada_solicitada = True
    control.save(update_fields=['parada_solicitada', 'actualizado'])
    return control.activo


def estado_servicio():
    control = ControlServicioIngestaMultifuente.objects.filter(pk=1).first()
    return {
        'activo': bool(control and control.activo and control.worker_hasta and control.worker_hasta > timezone.now()),
        'parada_solicitada': bool(control and control.parada_solicitada),
        'heartbeat': control.heartbeat.isoformat() if control and control.heartbeat else None,
        'fuentes': list(ProgramacionIngestaMultifuente.objects.order_by('fuente_id').values(
            'fuente_id', 'habilitada', 'acceso_revisado', 'aprobacion_operativa',
            'frecuencia_segundos', 'intervalo_segundos', 'solo_metadatos',
            'proxima_ejecucion', 'ultima_ejecucion',
        )),
        'trabajos_abiertos': list(TrabajoIngestaMultifuente.objects.filter(
            estado__in=ACTIVE_STATES,
        ).values('id', 'fuente_id', 'estado', 'entradas_snapshot', 'cursor',
                 'proxima_accion', 'codigo_error')),
    }


def reanudar_trabajo(trabajo_id, *, confirmar_revision=False):
    if confirmar_revision is not True:
        raise ValueError('La recuperación requiere confirmación explícita.')
    with transaction.atomic():
        trabajo = TrabajoIngestaMultifuente.objects.select_for_update().filter(pk=trabajo_id).first()
        if trabajo is None:
            raise ValueError('Trabajo de automatización inexistente.')
        if trabajo.estado != TrabajoIngestaMultifuente.Estado.REVISION_MANUAL:
            raise ValueError('El trabajo no requiere revisión manual.')
        plan = ProgramacionIngestaMultifuente.objects.get(fuente_id=trabajo.fuente_id)
        if trabajo.solo_metadatos != plan.solo_metadatos:
            raise ValueError('El modo del trabajo no coincide con su programación.')
        fuente = _fuente(
            trabajo.fuente_id, exigir_habilitada=True,
            permitir_solo_metadatos=trabajo.solo_metadatos,
        )
        if not (plan.habilitada and plan.acceso_revisado and plan.aprobacion_operativa):
            raise ValueError('La política operativa de la fuente sigue incompleta.')
        if trabajo.solo_metadatos:
            _validar_politica_metadata(fuente)
        control = _control_h5(fuente.identificador)
        if control and control.estado in (
            ControlSolicitudRSSMetadatos.Estado.EN_CURSO,
            ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL,
        ):
            raise ValueError('Resolver primero el bloqueo H5.6 mediante su comando explícito.')
        if trabajo.snapshot_capturado is None and trabajo.codigo_error.startswith('snapshot_'):
            raise ValueError('No hay snapshot confiable; la revisión debe decidir si se captura un feed nuevo.')
        trabajo.estado = TrabajoIngestaMultifuente.Estado.ESPERA
        trabajo.proxima_accion = timezone.now()
        trabajo.codigo_error = ''
        trabajo.finalizado = None
        trabajo.save()
    return trabajo
