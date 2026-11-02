"""Revisa en lotes noticias sin departamento, con simulación por defecto."""
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Publicacion, RevisionDepartamento
from core.services.clasificacion import departamento_por_texto
from core.services.clasificacion_departamentos import MAX_LOTE_IA, cliente_ia, consultar_ia


class Command(BaseCommand):
    help = 'Revisa publicaciones sin departamento. Por defecto simula sin llamar a IA ni escribir.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Guarda las decisiones y los departamentos confirmados.')
        parser.add_argument('--previsualizar-ia', action='store_true', help='Consulta Gemini sin escribir; consume cuota.')
        parser.add_argument('--sin-ia', action='store_true', help='Procesa sólo las reglas locales.')
        parser.add_argument('--revisar', action='store_true', help='Reevalúa abstenciones anteriores; nunca sobrescribe un departamento.')
        parser.add_argument('--limite', type=int, default=20, help='Noticias a intentar por lote (1 a 100).')
        parser.add_argument('--despues-de-id', type=int, default=0, help='Continúa con PK posteriores a este cursor.')
        parser.add_argument('--tamano-lote-ia', type=int, default=MAX_LOTE_IA,
                            help='Noticias por llamada a Gemini (1 a 10); bajarlo ayuda ante HTTP 503.')
        parser.add_argument('--pausa-ia', type=float, default=1.0, help='Segundos entre llamadas a Gemini (0 a 30).')

    @staticmethod
    def _guardar(publicacion, decision, metodo, modelo, revisar):
        with transaction.atomic():
            actual = Publicacion.objects.select_for_update().get(pk=publicacion.pk)
            anterior = RevisionDepartamento.objects.filter(publicacion=actual).first()
            if actual.departamento or (not revisar and anterior is not None):
                return False
            departamento = decision['departamento']
            if departamento:
                actual.departamento = departamento
                actual.save(update_fields=['departamento'])
            historial = list(anterior.historial) if anterior else []
            if anterior:
                historial.append({
                    'metodo': anterior.metodo, 'estado': anterior.estado,
                    'departamento': anterior.departamento, 'lugar': anterior.lugar,
                    'evidencia': anterior.evidencia, 'modelo': anterior.modelo,
                    'fecha_revision': anterior.fecha_revision.isoformat(),
                })
            RevisionDepartamento.objects.update_or_create(publicacion=actual, defaults={
                'metodo': metodo,
                'estado': decision['estado'],
                'departamento': departamento,
                'lugar': decision['lugar'],
                'evidencia': decision['evidencia'],
                'modelo': modelo,
                'historial': historial,
            })
        return True

    def handle(self, *args, **options):
        limite, cursor_inicial = options['limite'], options['despues_de_id']
        if not 1 <= limite <= 100:
            raise CommandError('--limite debe estar entre 1 y 100.')
        if cursor_inicial < 0:
            raise CommandError('--despues-de-id debe ser mayor o igual a cero.')
        if not 1 <= options['tamano_lote_ia'] <= MAX_LOTE_IA:
            raise CommandError(f'--tamano-lote-ia debe estar entre 1 y {MAX_LOTE_IA}.')
        if not 0 <= options['pausa_ia'] <= 30:
            raise CommandError('--pausa-ia debe estar entre 0 y 30 segundos.')
        if options['aplicar'] and options['previsualizar_ia']:
            raise CommandError('--aplicar y --previsualizar-ia son excluyentes.')
        if options['sin_ia'] and options['previsualizar_ia']:
            raise CommandError('--sin-ia y --previsualizar-ia son excluyentes.')

        pendientes = Publicacion.objects.filter(departamento='', pk__gt=cursor_inicial).order_by('pk')
        if not options['revisar']:
            pendientes = pendientes.filter(revision_departamento__isnull=True)
        lote = list(pendientes.only('id_publicacion_api', 'titulo', 'contenido', 'departamento')[:limite + 1])
        hay_mas = len(lote) > limite
        seleccionadas = lote[:limite]
        cursor = seleccionadas[-1].pk if seleccionadas else cursor_inicial
        reglas, requieren_ia = [], []
        for publicacion in seleccionadas:
            slug = departamento_por_texto(publicacion.titulo, publicacion.contenido)
            if slug:
                reglas.append((publicacion, {
                    'estado': RevisionDepartamento.Estado.ASIGNADO,
                    'departamento': slug, 'lugar': '', 'evidencia': '',
                }))
            else:
                requieren_ia.append(publicacion)

        consultar = (options['aplicar'] or options['previsualizar_ia']) and not options['sin_ia'] and bool(requieren_ia)
        cliente = None
        if consultar:
            try:
                cliente = cliente_ia()
            except RuntimeError as error:
                raise CommandError(str(error)) from error

        escritas = errores = abstenciones = omitidas = 0
        self.stdout.write(f'Seleccionadas: {len(seleccionadas)}. Resueltas por reglas: {len(reglas)}. '
                          f'Pendientes de IA: {len(requieren_ia)}.')
        for publicacion, decision in reglas:
            guardada = False
            if options['aplicar']:
                guardada = self._guardar(publicacion, decision, RevisionDepartamento.Metodo.REGLAS, '', options['revisar'])
                escritas += guardada
                omitidas += not guardada
            self.stdout.write(f'#{publicacion.pk}: reglas → {decision["departamento"]}'
                              + ((' (guardado).' if guardada else ' (omitido; cambió durante la revisión).')
                                 if options['aplicar'] else ' (simulación).'))

        if consultar:
            tamano_lote_ia = options['tamano_lote_ia']
            for inicio in range(0, len(requieren_ia), tamano_lote_ia):
                parte = requieren_ia[inicio:inicio + tamano_lote_ia]
                try:
                    decisiones, rechazadas = consultar_ia(parte, cliente=cliente)
                except Exception as error:
                    errores += len(parte)
                    codigo = getattr(error, 'code', None)
                    codigo_http = f', HTTP {codigo}' if type(codigo) is int and 400 <= codigo <= 599 else ''
                    self.stderr.write(
                        f'IA: lote desde #{parte[0].pk} sin respuesta válida '
                        f'({type(error).__name__}{codigo_http}).'
                    )
                    continue
                errores += len(rechazadas)
                for pk, codigo in sorted(rechazadas.items()):
                    self.stderr.write(f'#{pk}: respuesta IA descartada ({codigo}).')
                for publicacion in parte:
                    decision = decisiones.get(publicacion.pk)
                    if decision is None:
                        continue
                    if decision['estado'] != RevisionDepartamento.Estado.ASIGNADO:
                        abstenciones += 1
                    guardada = False
                    if options['aplicar']:
                        guardada = self._guardar(publicacion, decision, RevisionDepartamento.Metodo.IA,
                                                cliente.model_name, options['revisar'])
                        escritas += guardada
                        omitidas += not guardada
                    detalle = (f' | {decision["lugar"]}: {decision["evidencia"]}'
                               if options['previsualizar_ia'] and decision['evidencia'] else '')
                    self.stdout.write(f'#{publicacion.pk}: IA → {decision["estado"]}'
                                      + (f' ({decision["departamento"]})' if decision['departamento'] else '')
                                      + detalle
                                      + ((' (guardado).' if guardada else ' (omitido; cambió durante la revisión).')
                                         if options['aplicar'] else ' (previsualización).'))
                if inicio + tamano_lote_ia < len(requieren_ia) and options['pausa_ia']:
                    time.sleep(options['pausa_ia'])
        elif requieren_ia:
            self.stdout.write('No se consultó a la IA; estas noticias permanecen sin departamento.')

        self.stdout.write(f'Decisiones guardadas: {escritas}. Abstenciones IA: {abstenciones}. '
                          f'Omitidas por cambios concurrentes: {omitidas}. Errores IA: {errores}. Cursor: {cursor}.')
        if errores:
            raise CommandError(
                f'{errores} decisiones sin resolver. Reintentá desde '
                f'--despues-de-id={cursor_inicial}; las guardadas no se repiten.'
            )
        if hay_mas:
            self.stdout.write(f'Hay más candidatas. Continuá con --despues-de-id={cursor}.')
        else:
            self.stdout.write('Fin del conjunto posterior al cursor inicial.')
