import json
import signal
import threading

from django.core.management.base import BaseCommand, CommandError

from core.services import planificador_multifuente as planificador


class Command(BaseCommand):
    help = 'Configura y ejecuta ciclos periódicos multifuente; no se inicia automáticamente con Django.'

    def add_arguments(self, parser):
        modos = parser.add_mutually_exclusive_group(required=True)
        modos.add_argument('--configurar', action='store_true')
        modos.add_argument('--habilitar', action='store_true')
        modos.add_argument('--deshabilitar', action='store_true')
        modos.add_argument('--una-vez', action='store_true')
        modos.add_argument('--iniciar', action='store_true')
        modos.add_argument('--detener', action='store_true')
        modos.add_argument('--estado', action='store_true')
        modos.add_argument('--reanudar-trabajo', type=int, metavar='ID')
        parser.add_argument('--fuente')
        parser.add_argument(
            '--intervalo-segundos', type=int,
            help='Compatibilidad: configura frecuencia RSS y mínimo HTTP al mismo valor.',
        )
        parser.add_argument('--frecuencia-segundos', type=int, help='Cadencia entre consultas RSS.')
        parser.add_argument('--intervalo-http-segundos', type=int, help='Mínimo entre solicitudes HTTP.')
        parser.add_argument(
            '--modo', choices=('articulos', 'metadatos'), default=None,
            help='Modo por fuente; metadatos persiste únicamente título, fecha, fuente y URL.',
        )
        parser.add_argument('--confirmar-revision-acceso', action='store_true')
        parser.add_argument('--confirmar-aprobacion-operativa', action='store_true')
        parser.add_argument('--confirmar-revision', action='store_true')
        parser.add_argument('--max-fuentes', type=int, default=5)
        parser.add_argument('--poll-segundos', type=int, default=15)

    def handle(self, *args, **opts):
        try:
            if opts['configurar']:
                if not opts['fuente']:
                    raise ValueError('--fuente es obligatorio con --configurar.')
                salida = planificador.configurar_fuente(
                    opts['fuente'],
                    intervalo_segundos=opts['intervalo_segundos'],
                    frecuencia_segundos=opts['frecuencia_segundos'],
                    intervalo_http_segundos=opts['intervalo_http_segundos'],
                    solo_metadatos=(opts['modo'] == 'metadatos') if opts['modo'] else None,
                )
                resultado = {
                    'fuente_id': salida.fuente_id, 'habilitada': salida.habilitada,
                    'frecuencia_segundos': salida.frecuencia_segundos,
                    'intervalo_segundos': salida.intervalo_segundos,
                    'intervalo_http_segundos': salida.intervalo_segundos,
                    'modo': 'metadatos' if salida.solo_metadatos else 'articulos',
                }
            elif opts['habilitar']:
                if not opts['fuente']:
                    raise ValueError('--fuente es obligatorio con --habilitar.')
                salida = planificador.habilitar_fuente(
                    opts['fuente'],
                    confirmar_revision_acceso=opts['confirmar_revision_acceso'],
                    confirmar_aprobacion_operativa=opts['confirmar_aprobacion_operativa'],
                )
                resultado = {'fuente_id': salida.fuente_id, 'habilitada': salida.habilitada}
            elif opts['deshabilitar']:
                if not opts['fuente']:
                    raise ValueError('--fuente es obligatorio con --deshabilitar.')
                salida = planificador.deshabilitar_fuente(opts['fuente'])
                resultado = {'fuente_id': salida.fuente_id, 'habilitada': salida.habilitada}
            elif opts['una_vez']:
                resultado = planificador.ejecutar_ciclo(max_fuentes=opts['max_fuentes'])
            elif opts['iniciar']:
                evento = threading.Event()
                anteriores = {}
                def detener(signum, frame):
                    evento.set()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    anteriores[sig] = signal.signal(sig, detener)
                try:
                    ciclos = planificador.iniciar_worker(
                        intervalo_poll=opts['poll_segundos'], max_fuentes=opts['max_fuentes'],
                        stop_event=evento,
                    )
                finally:
                    for sig, handler in anteriores.items():
                        signal.signal(sig, handler)
                resultado = {'detenido': True, 'ciclos': ciclos}
            elif opts['detener']:
                resultado = {'detencion_solicitada': planificador.solicitar_detencion()}
            elif opts['estado']:
                resultado = planificador.estado_servicio()
            else:
                salida = planificador.reanudar_trabajo(
                    opts['reanudar_trabajo'], confirmar_revision=opts['confirmar_revision'],
                )
                resultado = {'id': salida.pk, 'estado': salida.estado,
                             'proxima_accion': salida.proxima_accion.isoformat()
                             if salida.proxima_accion else None}
        except (ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, sort_keys=True, default=str))
