"""H3.2: cola durable de altas H3.1, sin caducidad ni reenvíos inciertos.

H3.1 encola sólo publicaciones nuevas en su propia transacción. La adquisición
usa token y marca de envío condicional: un competidor no modifica otro intento.
Las reservas sin marca de envío pueden recuperarse con un token nuevo; el token
anterior ya no puede enviar. Crash tras marcar envío requiere revisión manual.
"""
import hashlib
import json
import time
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from core.models import (AliasURLPublicacion, Locacion, ProcesamientoIAMultifuente,
                         Publicacion, Sentimiento)
from core.services.fuentes_rss import FUENTES_RSS
from core.services.parametros import entero_positivo, segundos_validos
from core.services.persistencia_multifuente import persistir_lote
from core.services.autorizacion_gemini import fuente_autorizada, publicacion_multifuente_autorizada


def _opciones(batch_size, timeout_segundos, pausa_segundos):
    entero_positivo(batch_size, 'batch_size')
    if batch_size > 20:
        raise ValueError('batch_size máximo: 20.')
    segundos_validos(timeout_segundos, 'timeout_segundos')
    segundos_validos(pausa_segundos, 'pausa_segundos', permitir_cero=True)


def _sin_transaccion():
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError('H3.2 debe ejecutarse después del commit de persistencia, sin transacción externa.')


def _huella(pub):
    texto = json.dumps([pub.titulo, pub.contenido, pub.contenido_completo, pub.fuente, pub.url,
                       pub.hash_origen, pub.id_registro_id], ensure_ascii=False)
    return hashlib.sha256(texto.encode()).hexdigest()


def _listos():
    return Q(estado='PENDIENTE') | Q(estado='EN_PROCESO', enviado__isnull=True)


def filtro_cliente_global():
    """Filtra antes del cupo; no cambia los candidatos ajenos a H3.1."""
    editorial_multifuente = Q(fuente__in=[f.nombre for f in FUENTES_RSS])
    registro_multifuente = Q(id_registro__fuentes_api='RSS multifuente')
    listos = (Q(procesamiento_ia_multifuente__estado='PENDIENTE')
              | Q(procesamiento_ia_multifuente__estado='EN_PROCESO',
                  procesamiento_ia_multifuente__enviado__isnull=True))
    sin_resultados = (~Q(Exists(Sentimiento.objects.filter(id_publicacion_api_id=OuterRef('pk'))))
                      & ~Q(Exists(Locacion.objects.filter(id_publicacion_api_id=OuterRef('pk')))))
    alias = Q(Exists(AliasURLPublicacion.objects.filter(publicacion_id=OuterRef('pk'))))
    autorizadas = Q(fuente__in=[f.nombre for f in FUENTES_RSS if fuente_autorizada(f.identificador)])
    # La fuente editorial identifica multifuente incluso si falta o está mal el registro.
    # Un registro inconsistente nunca cae al camino legacy de El Territorio.
    return Q(contenido_completo=True, contenido__regex=r'\S') & (~editorial_multifuente | (editorial_multifuente & registro_multifuente & autorizadas
                                    & listos & sin_resultados & alias)
                                    )


def _elegible(pub, registro_id, hash_origen):
    if (not pub.tiene_cuerpo_completo or type(registro_id) is not int or pub.id_registro_id is None
            or pub.id_registro_id != registro_id or pub.hash_origen != hash_origen
            or pub.id_registro.fuentes_api != 'RSS multifuente'):
        return False
    fuente = next((f for f in FUENTES_RSS if f.nombre == pub.fuente), None)
    if fuente is None or not AliasURLPublicacion.objects.filter(
        publicacion=pub, fuente=fuente.identificador
    ).exists():
        return False
    return (publicacion_multifuente_autorizada(pub)
            and not pub.procesado_ia
            and not Sentimiento.objects.filter(id_publicacion_api=pub).exists()
            and not Locacion.objects.filter(id_publicacion_api=pub).exists()
            and ProcesamientoIAMultifuente.objects.filter(_listos(), publicacion=pub).exists())


def _reservar(pk, registro_id, hash_origen):
    with transaction.atomic():
        pub = Publicacion.objects.select_for_update(of=('self',)).select_related('id_registro').get(pk=pk)
        if not _elegible(pub, registro_id, hash_origen):
            return None
        trabajo = ProcesamientoIAMultifuente.objects.select_for_update().get(publicacion=pub)
        # La marca de envío puede cambiar después de la consulta de elegibilidad.
        # Revalidar bajo el mismo bloqueo que protege el cambio de propietario.
        if trabajo.estado not in ('PENDIENTE', 'EN_PROCESO') or trabajo.enviado is not None:
            return None
        token = uuid4()
        trabajo.token_intento = token
        trabajo.estado = 'EN_PROCESO'
        trabajo.huella_texto = _huella(pub)
        trabajo.iniciado = timezone.now()
        trabajo.codigo_error = ''
        trabajo.finalizado = None
        trabajo.save(update_fields=['token_intento', 'estado', 'huella_texto', 'iniciado', 'codigo_error', 'finalizado'])
        return pub, token


def _marcar_envio(pk, token):
    return ProcesamientoIAMultifuente.objects.filter(
        publicacion_id=pk, token_intento=token, estado='EN_PROCESO', enviado__isnull=True
    ).update(enviado=timezone.now()) == 1


def _error(pk, token, codigo, *, incierto=False):
    if token is None:
        return 0
    return ProcesamientoIAMultifuente.objects.filter(
        publicacion_id=pk, token_intento=token, estado='EN_PROCESO'
    ).update(estado='INCIERTO' if incierto else 'ERROR', codigo_error=codigo, finalizado=timezone.now())


def _cancelar_preenvio(pk, token):
    return ProcesamientoIAMultifuente.objects.filter(
        publicacion_id=pk, token_intento=token, estado='EN_PROCESO', enviado__isnull=True
    ).update(estado='PENDIENTE', token_intento=None, iniciado=None)


def _guardar_resultado(pub, token, data):
    with transaction.atomic():
        actual = Publicacion.objects.select_for_update().get(pk=pub.pk)
        trabajo = ProcesamientoIAMultifuente.objects.select_for_update().get(publicacion=actual)
        if trabajo.estado != 'EN_PROCESO' or trabajo.token_intento != token:
            return False
        if (not actual.tiene_cuerpo_completo or _huella(actual) != trabajo.huella_texto or actual.procesado_ia
                or Sentimiento.objects.filter(id_publicacion_api=actual).exists()
                or Locacion.objects.filter(id_publicacion_api=actual).exists()):
            _error(pub.pk, token, 'texto_o_resultados_modificados')
            return False
        Sentimiento.objects.create(id_publicacion_api=actual, polaridad=data['polaridad'], confianza=data['confianza'])
        for loc in data['localidades']:
            Locacion.objects.create(id_publicacion_api=actual, location=loc['nombre'],
                                    latitud=loc['latitud'], longitud=loc['longitud'])
        actual.procesado_ia = True
        actual.save(update_fields=['procesado_ia'])
        trabajo.estado = 'COMPLETADO'
        trabajo.finalizado = timezone.now()
        trabajo.save(update_fields=['estado', 'finalizado'])
        return True


def _procesar(candidatos, *, dry_run, batch_size, timeout_segundos, pausa_segundos, cliente):
    if not dry_run:
        _sin_transaccion()
    resultado = dict(dry_run=dry_run, procesadas=0, previstas=0, omitidas=0, llamadas=0, errores=[])
    vistos = set()
    for pk, registro_id, hash_origen in candidatos:
        if type(pk) is not int or pk <= 0 or pk in vistos:
            continue
        vistos.add(pk)
        token = None
        enviado = False
        try:
            if (resultado['previstas'] if dry_run else resultado['llamadas']) >= batch_size:
                resultado['omitidas'] += 1  # La fila PENDIENTE queda durable para otra ejecución.
                continue
            if dry_run:
                pub = Publicacion.objects.select_related('id_registro').get(pk=pk)
                resultado['previstas' if _elegible(pub, registro_id, hash_origen) else 'omitidas'] += 1
                continue
            from core.services.gemini_cliente import SYSTEM_PROMPT, gemini_cliente, validar_respuesta_gemini
            servicio = cliente if cliente is not None else gemini_cliente
            if servicio.client is None or servicio.types is None:
                resultado['errores'].append(dict(publicacion_id=pk, codigo='servicio_no_disponible'))
                continue
            # Configuración y pausa antes de adquirir: si fallan, sigue PENDIENTE.
            config = servicio.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT, response_mime_type='application/json', temperature=0.1,
                http_options=servicio.types.HttpOptions(timeout=max(1, int(timeout_segundos * 1000)),
                    retry_options=servicio.types.HttpRetryOptions(attempts=1)))
            if resultado['llamadas'] and pausa_segundos:
                time.sleep(pausa_segundos)
            reserva = _reservar(pk, registro_id, hash_origen)
            if reserva is None:
                resultado['omitidas'] += 1
                continue
            pub, token = reserva
            _sin_transaccion()
            # Revalidar en el último punto antes del envío. Si se revocó,
            # liberar sólo la reserva propia y conservar PENDIENTE.
            if not publicacion_multifuente_autorizada(pub):
                _cancelar_preenvio(pk, token)
                resultado['omitidas'] += 1
                continue
            if not _marcar_envio(pk, token):
                resultado['omitidas'] += 1  # Otro intento recuperó la reserva antes del envío.
                continue
            enviado = True
            resultado['llamadas'] += 1
            try:
                response = servicio.client.models.generate_content(
                    model=servicio.model_name, contents=f'Título: {pub.titulo}\nContenido: {pub.contenido}', config=config)
            except Exception:
                _error(pk, token, 'llamada_gemini', incierto=True)
                resultado['errores'].append(dict(publicacion_id=pk, codigo='llamada_gemini'))
                continue
            try:
                data = validar_respuesta_gemini(response.text)
            except (ValueError, TypeError, AttributeError, RecursionError):
                _error(pk, token, 'validacion_respuesta')
                resultado['errores'].append(dict(publicacion_id=pk, codigo='validacion_respuesta'))
                continue
            if _guardar_resultado(pub, token, data):
                resultado['procesadas'] += 1
            else:
                resultado['omitidas'] += 1
        except Exception:
            if token is not None:
                try:
                    if enviado:
                        _error(pk, token, 'persistencia_ia')
                    else:
                        _cancelar_preenvio(pk, token)
                except Exception:
                    pass  # Nunca liberar un envío incierto ni invalidar otro token.
            resultado['errores'].append(dict(publicacion_id=pk, codigo='persistencia_ia'))
    return resultado


def procesar_nuevas(resultado_ingesta, *, dry_run=False, batch_size=5,
                     timeout_segundos=30, pausa_segundos=12, cliente=None):
    """GUARDADA se verifica contra el recibo; DUPLICADA sólo recupera cola previa.

    La cola prueba el alta original H3.1: nunca se encolan históricos desde aquí.
    No hay caducidad; sólo se envían estados que todavía no tienen envío marcado.
    """
    if type(dry_run) is not bool or not isinstance(resultado_ingesta, dict):
        raise ValueError('Parámetros inválidos.')
    _opciones(batch_size, timeout_segundos, pausa_segundos)
    dry_run = dry_run or resultado_ingesta.get('dry_run') is True
    candidatos = []
    for item in resultado_ingesta.get('noticias', []):
        if not isinstance(item, dict):
            continue
        if item.get('estado') == 'GUARDADA':
            candidatos.append((item.get('publicacion_id'), resultado_ingesta.get('registro_id'), item.get('hash_origen')))
        elif item.get('estado') == 'DUPLICADA' and type(item.get('publicacion_id')) is int:
            candidatos.extend(Publicacion.objects.filter(
                pk=item['publicacion_id'], procesamiento_ia_multifuente__isnull=False
            ).values_list('pk', 'id_registro_id', 'hash_origen'))
    return _procesar(candidatos, dry_run=dry_run, batch_size=batch_size, timeout_segundos=timeout_segundos,
                     pausa_segundos=pausa_segundos, cliente=cliente)


def procesar_pendientes_multifuente(*, dry_run=False, batch_size=5,
                                    timeout_segundos=30, pausa_segundos=12, cliente=None):
    """Recupera altas encoladas, aun sin recibo original; no descubre históricos."""
    if type(dry_run) is not bool:
        raise ValueError('dry_run debe ser booleano.')
    _opciones(batch_size, timeout_segundos, pausa_segundos)
    candidatos = list(Publicacion.objects.filter(
        filtro_cliente_global(), procesamiento_ia_multifuente__isnull=False, procesado_ia=False
    ).order_by('pk').values_list('pk', 'id_registro_id', 'hash_origen')[:batch_size])
    return _procesar(candidatos, dry_run=dry_run, batch_size=batch_size, timeout_segundos=timeout_segundos,
                     pausa_segundos=pausa_segundos, cliente=cliente)


def persistir_y_procesar(entradas, *, dry_run=False, batch_size=5,
                         timeout_segundos=30, pausa_segundos=12, cliente=None):
    _opciones(batch_size, timeout_segundos, pausa_segundos)
    if type(dry_run) is not bool:
        raise ValueError('dry_run debe ser booleano.')
    if not dry_run:
        _sin_transaccion()
    ingesta = persistir_lote(entradas, dry_run=dry_run)
    return {'ingesta': ingesta, 'ia': procesar_nuevas(ingesta, dry_run=dry_run, batch_size=batch_size,
        timeout_segundos=timeout_segundos, pausa_segundos=pausa_segundos, cliente=cliente)}


def procesar_desde_cliente_global(pub, cliente):
    if (getattr(pub, 'fuente', None) not in {f.nombre for f in FUENTES_RSS}
            or not getattr(pub, 'id_registro_id', None)):
        return None
    if pub.id_registro.fuentes_api != 'RSS multifuente':
        return None
    recibo = {'registro_id': pub.id_registro_id, 'noticias': [
        {'estado': 'GUARDADA', 'publicacion_id': pub.pk, 'hash_origen': pub.hash_origen}]}
    return procesar_nuevas(recibo, cliente=cliente, batch_size=1, pausa_segundos=0)
