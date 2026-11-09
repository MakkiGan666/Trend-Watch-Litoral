from .busqueda_texto_v1 import TextoComparableV1
from .imagenes import es_portada_generica

from django.db import models, router, transaction
from django.utils import timezone
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from contextvars import ContextVar


_actualizacion_masiva_publicacion_validada = ContextVar(
    'actualizacion_masiva_publicacion_validada', default=False,
)


def ruta_imagen_publicacion(instance, filename):
    extension = filename.rsplit('.', 1)[-1].lower()
    return f'publicaciones/{uuid4().hex}.{extension}'


class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    fecha_nacimiento = models.DateField(null=True, blank=True)
    celular = models.CharField(max_length=30, blank=True)


class PublicacionGuardada(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='noticias_guardadas')
    publicacion = models.ForeignKey('Publicacion', on_delete=models.CASCADE, related_name='guardados')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion', '-pk']
        constraints = [models.UniqueConstraint(fields=['usuario', 'publicacion'], name='guardado_unico_usuario_noticia')]


class ClicPublicacion(models.Model):
    """Lectura única por usuario y noticia, con actividad reciente para tendencias."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='clics_noticias')
    publicacion = models.ForeignKey('Publicacion', on_delete=models.CASCADE, related_name='clics')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    ultima_visita = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['usuario', 'publicacion'], name='clic_unico_usuario_noticia')]
        indexes = [models.Index(fields=['fecha_creacion'], name='clic_noticia_fecha_idx')]


class Role(models.Model):
    id_rol = models.AutoField(primary_key=True)
    nombre_rol = models.CharField(max_length=100)

    class Meta:
        db_table = 'Roles'

    def __str__(self):
        return self.nombre_rol


class User(models.Model):
    id_user = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=20)
    email = models.CharField(max_length=20)
    password_hash = models.CharField(max_length=255)
    id_rol = models.ForeignKey(Role, on_delete=models.CASCADE, db_column='id_rol')

    class Meta:
        db_table = 'User'

    def __str__(self):
        return self.nombre


class RegistroDatos(models.Model):
    id_registro = models.AutoField(primary_key=True)
    fuentes_api = models.CharField(max_length=100)
    fecha_ejecucion = models.DateTimeField()
    estado = models.CharField(max_length=50)
    lenguaje = models.CharField(max_length=50)

    class Meta:
        db_table = 'Registro_Datos'

    def __str__(self):
        return f"Registro {self.id_registro} - {self.fuentes_api}"


class ControlSolicitudRSSMetadatos(models.Model):
    """Última solicitud y pausa impuesta por el servidor para cada feed opt-in."""

    class Estado(models.TextChoices):
        LIBRE = 'LIBRE', 'Libre'
        EN_CURSO = 'EN_CURSO', 'Solicitud en curso'
        ESPERA = 'ESPERA', 'Espera activa'
        REVISION_MANUAL = 'REVISION_MANUAL', 'Revisión manual requerida'

    fuente_id = models.CharField(max_length=64, unique=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.LIBRE)
    ultimo_intento = models.DateTimeField(null=True, blank=True)
    retry_after_hasta = models.DateTimeField(null=True, blank=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_control_solicitud_rss_metadatos'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=['LIBRE', 'EN_CURSO', 'ESPERA', 'REVISION_MANUAL']),
                name='control_rss_estado_valido',
            ),
            models.CheckConstraint(
                condition=(~models.Q(estado='ESPERA') | models.Q(retry_after_hasta__isnull=False)),
                name='control_rss_espera_con_fecha',
            ),
        ]

    def __str__(self):
        return f'Control RSS metadatos: {self.fuente_id}'


class PublicacionQuerySet(models.QuerySet):
    def con_cuerpo_completo(self):
        """Sólo artículos con bandera y texto no blanco; excluye legacy vacíos."""
        return self.filter(contenido_completo=True, contenido__regex=r'\S')

    def update(self, **kwargs):
        campos_cuerpo = {'contenido', 'contenido_completo'}
        if not campos_cuerpo.intersection(kwargs):
            return super().update(**kwargs)
        if _actualizacion_masiva_publicacion_validada.get():
            return models.QuerySet.update(self, **kwargs)

        # Las expresiones SQL no permiten validar el estado resultante en Python.
        # Para estos dos campos se exige usar valores literales y una transición
        # validada bajo bloqueo; el resto de campos conserva update() normal.
        if 'contenido' in kwargs and not isinstance(kwargs['contenido'], str):
            raise ValidationError('Actualizá el cuerpo mediante una transición explícita.')
        if 'contenido_completo' in kwargs and type(kwargs['contenido_completo']) is not bool:
            raise ValidationError('Actualizá la disponibilidad del cuerpo con un booleano explícito.')

        using = self.db
        with transaction.atomic(using=using):
            actuales = list(self.using(using).select_for_update().values(
                'pk', 'contenido', 'contenido_completo',
            ))
            for actual in actuales:
                contenido = kwargs.get('contenido', actual['contenido'])
                completo = kwargs.get('contenido_completo', actual['contenido_completo'])
                if _estado_cuerpo_valido(contenido, completo):
                    continue
                # Compatibilidad: se permite una escritura no-op del estado
                # histórico vacío que ya existía antes de H5.3.
                estado_legacy_sin_cambios = (
                    actual['contenido_completo'] is True
                    and not (actual['contenido'] or '').strip()
                    and contenido == actual['contenido']
                    and completo is True
                )
                if not estado_legacy_sin_cambios:
                    raise ValidationError(
                        'La actualización dejaría un estado incoherente entre cuerpo y disponibilidad.'
                    )
            if not actuales:
                return 0
            # Limitar el UPDATE al conjunto bloqueado/validado evita que una
            # fila insertada concurrentemente entre SELECT y UPDATE eluda el
            # chequeo por condición original.
            ids_validados = {fila['pk'] for fila in actuales}
            return models.QuerySet.update(
                self.using(using).filter(pk__in=ids_validados), **kwargs,
            )

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        for obj in objs:
            if not _estado_cuerpo_valido(obj.contenido, obj.contenido_completo):
                _validar_estado_cuerpo(obj.contenido, obj.contenido_completo)
        campos_conflicto = set(kwargs.get('update_fields') or ())
        if kwargs.get('update_conflicts') and campos_conflicto.intersection(
                {'contenido', 'contenido_completo'}):
            raise ValidationError(
                'No se permiten upserts masivos sobre cuerpo o disponibilidad; usá una transición validada.'
            )
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        fields = list(fields)
        campos_cuerpo = {'contenido', 'contenido_completo'}
        nombres = {getattr(campo, 'name', campo) for campo in fields}
        if not campos_cuerpo.intersection(nombres):
            return super().bulk_update(objs, fields, batch_size=batch_size)

        objs = list(objs)
        if any(not hasattr(obj, 'pk') or obj.pk is None for obj in objs):
            return super().bulk_update(objs, fields, batch_size=batch_size)
        if 'contenido' in nombres and any(not isinstance(obj.contenido, str) for obj in objs):
            raise ValidationError('Actualizá el cuerpo mediante una transición explícita.')
        if 'contenido_completo' in nombres and any(type(obj.contenido_completo) is not bool for obj in objs):
            raise ValidationError('Actualizá la disponibilidad del cuerpo con un booleano explícito.')

        using = self.db
        with transaction.atomic(using=using):
            actuales = {
                fila['pk']: fila
                for fila in self.model._base_manager.using(using).select_for_update()
                .filter(pk__in={obj.pk for obj in objs})
                .values('pk', 'contenido', 'contenido_completo')
            }
            for obj in objs:
                anterior = actuales.get(obj.pk)
                if anterior is None:
                    continue  # Django base valida la fila inexistente.
                contenido = obj.contenido if 'contenido' in nombres else anterior['contenido']
                completo = obj.contenido_completo if 'contenido_completo' in nombres else anterior['contenido_completo']
                if _estado_cuerpo_valido(contenido, completo):
                    continue
                estado_legacy_sin_cambios = (
                    anterior['contenido_completo'] is True
                    and not (anterior['contenido'] or '').strip()
                    and contenido == anterior['contenido']
                    and completo is True
                )
                if not estado_legacy_sin_cambios:
                    raise ValidationError(
                        'La actualización masiva dejaría un estado incoherente entre cuerpo y disponibilidad.'
                    )

            token = _actualizacion_masiva_publicacion_validada.set(True)
            try:
                return super().bulk_update(objs, fields, batch_size=batch_size)
            finally:
                _actualizacion_masiva_publicacion_validada.reset(token)


class PublicacionManager(models.Manager.from_queryset(PublicacionQuerySet)):
    def get_queryset(self):
        # Sólo son necesarios para filtrar en SQL; no se presentan ni se leen
        # desde instancias en las vistas. Evitar duplicar texto transferido.
        return super().get_queryset().defer('titulo_busqueda', 'contenido_busqueda')


class Publicacion(models.Model):
    objects = PublicacionManager()

    id_publicacion_api = models.AutoField(primary_key=True)
    hash_origen = models.CharField(max_length=64, unique=True, default="")
    fuente = models.CharField(max_length=100, default='El Territorio')  # <-- Agregado default
    titulo = models.CharField(max_length=255, default="")
    contenido = models.TextField(blank=True)
    # Los registros existentes y el pipeline completo mantienen el valor True.
    # Sólo una ficha declarada sin cuerpo puede guardar contenido vacío.
    contenido_completo = models.BooleanField(default=True)
    titulo_busqueda = models.GeneratedField(
        expression=TextoComparableV1('titulo'), output_field=models.TextField(), db_persist=True, serialize=False,
    )
    contenido_busqueda = models.GeneratedField(
        expression=TextoComparableV1('contenido'), output_field=models.TextField(), db_persist=True, serialize=False,
    )
    # El Territorio usa slugs largos: 200 (el valor por defecto) descartaba noticias reales.
    url = models.URLField(max_length=500, default="")
    # Se enlaza la foto original del medio (no se copia); la web le superpone el crédito.
    imagen_url = models.URLField(max_length=500, blank=True, default="")
    imagen_archivo = models.ImageField(upload_to=ruta_imagen_publicacion, blank=True, default='')
    fecha_publicacion = models.DateTimeField(null=True, blank=True)
    # Slug de core.localidades.DEPARTAMENTOS; vacío si no se pudo identificar.
    departamento = models.CharField(max_length=30, blank=True, default="")
    fecha_captura = models.DateTimeField(default=timezone.now)
    procesado_ia = models.BooleanField(default=False)
    id_registro = models.ForeignKey('RegistroDatos', on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        db_table = 'Publicacion'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(contenido_completo=True) | models.Q(contenido=''),
                name='publicacion_sin_cuerpo_vacio',
            ),
        ]
        permissions = [
            ('ejecutar_scraping', 'Puede ejecutar scraping'),
            ('procesar_ia', 'Puede ejecutar procesamiento IA'),
        ]

    def __str__(self):
        return self.titulo

    @property
    def tiene_cuerpo_completo(self):
        return self.contenido_completo is True and bool((self.contenido or '').strip())

    def clean(self):
        super().clean()
        _validar_estado_cuerpo(self.contenido, self.contenido_completo)

    def save(self, *args, **kwargs):
        # Incluir pre_save/post_save en la misma transacción que el texto.
        # Así un fallo de etiquetas no deja el artículo guardado sin sincronizar.
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        kwargs['using'] = using
        campos_cuerpo = {'contenido', 'contenido_completo'}
        update_fields = kwargs.get('update_fields')
        with transaction.atomic(using=using):
            validar_cuerpo = (
                self._state.adding or update_fields is None
                or bool(campos_cuerpo & set(update_fields))
            )
            if validar_cuerpo:
                anterior = None
                if not self._state.adding:
                    anterior = (type(self).objects.using(using).select_for_update()
                                .filter(pk=self.pk)
                                .values('contenido', 'contenido_completo').first())
                campos = set(update_fields) if update_fields is not None else campos_cuerpo
                contenido_final = self.contenido if 'contenido' in campos else (anterior or {}).get('contenido', self.contenido)
                completo_final = (self.contenido_completo if 'contenido_completo' in campos
                                  else (anterior or {}).get('contenido_completo', self.contenido_completo))
                if not _estado_cuerpo_valido(contenido_final, completo_final):
                    estado_legacy_sin_cambios = (
                        anterior is not None
                        and anterior['contenido_completo'] is True
                        and not (anterior['contenido'] or '').strip()
                        and contenido_final == anterior['contenido']
                        and completo_final is True
                    )
                    if not estado_legacy_sin_cambios:
                        _validar_estado_cuerpo(contenido_final, completo_final)
            return super().save(*args, **kwargs)

    @property
    def imagen_publica_url(self):
        if self.imagen_archivo:
            return self.imagen_archivo.url
        return '' if es_portada_generica(self.imagen_url) else self.imagen_url


def _estado_cuerpo_valido(contenido, completo):
    tiene_texto = isinstance(contenido, str) and bool(contenido.strip())
    return (completo is True and tiene_texto) or (completo is False and not tiene_texto)


def _validar_estado_cuerpo(contenido, completo):
    if not _estado_cuerpo_valido(contenido, completo):
        if completo is True:
            raise ValidationError({'contenido': 'Una publicación con cuerpo completo requiere contenido.'})
        raise ValidationError({'contenido': 'Una ficha sin cuerpo completo no puede guardar contenido.'})


class AliasURLPublicacion(models.Model):
    """Identidades RSS/canónicas conocidas, separadas de los hashes históricos."""
    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='aliases_urls')
    fuente = models.CharField(max_length=100)  # Identificador canónico del catálogo H1.1.
    url_normalizada = models.URLField(max_length=500)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['fuente', 'url_normalizada'], name='alias_url_unico_por_fuente'),
        ]


class ProcesamientoIAMultifuente(models.Model):
    """Reserva durable de un único envío: un fallo incierto no habilita reenvío."""
    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Todavía no enviado'
        EN_PROCESO = 'EN_PROCESO', 'Intento adquirido'
        COMPLETADO = 'COMPLETADO', 'Resultado guardado'
        ERROR = 'ERROR', 'Respuesta o persistencia fallida; requiere revisión'
        INCIERTO = 'INCIERTO', 'Envío de resultado desconocido; no reenviar'

    publicacion = models.OneToOneField(Publicacion, primary_key=True, on_delete=models.CASCADE,
                                      related_name='procesamiento_ia_multifuente')
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    huella_texto = models.CharField(max_length=64, blank=True, default='')
    token_intento = models.UUIDField(null=True, blank=True)
    codigo_error = models.CharField(max_length=40, blank=True, default='')
    creado = models.DateTimeField(default=timezone.now)
    iniciado = models.DateTimeField(null=True, blank=True)
    enviado = models.DateTimeField(null=True, blank=True)
    finalizado = models.DateTimeField(null=True, blank=True)


class RevisionDepartamento(models.Model):
    """Decisión auditable para noticias que llegaron sin departamento."""

    class Metodo(models.TextChoices):
        REGLAS = 'reglas', 'Reglas locales'
        IA = 'ia', 'IA'

    class Estado(models.TextChoices):
        ASIGNADO = 'asignado', 'Departamento asignado'
        PROVINCIAL = 'provincial', 'Misiones sin departamento claro'
        FUERA = 'fuera', 'Fuera de Misiones'
        VARIOS = 'varios', 'Varios departamentos'
        SIN_EVIDENCIA = 'sin_evidencia', 'Sin evidencia suficiente'

    publicacion = models.OneToOneField(Publicacion, on_delete=models.CASCADE, related_name='revision_departamento')
    metodo = models.CharField(max_length=8, choices=Metodo.choices)
    estado = models.CharField(max_length=16, choices=Estado.choices)
    departamento = models.CharField(max_length=30, blank=True, default='')
    lugar = models.CharField(max_length=80, blank=True, default='')
    evidencia = models.CharField(max_length=240, blank=True, default='')
    modelo = models.CharField(max_length=80, blank=True, default='')
    historial = models.JSONField(default=list, blank=True)
    fecha_revision = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Revisión territorial de publicación #{self.publicacion_id}: {self.get_estado_display()}'


class Categoria(models.Model):
    id_categoria = models.AutoField(primary_key=True)
    nombre_categoria = models.CharField(max_length=100)

    class Meta:
        db_table = 'Categorias'

    def __str__(self):
        return self.nombre_categoria


class Trend(models.Model):
    # Identidad de tendencias automáticas; los registros históricos se conservan.
    clave = models.CharField(max_length=50, null=True, blank=True, unique=True, editable=False)
    id_trends = models.AutoField(primary_key=True)
    relevancia = models.CharField(max_length=50)
    intervalos_periodo = models.CharField(max_length=100)

    class Meta:
        db_table = 'Trends'

    def __str__(self):
        return f"Trend {self.id_trends} - {self.relevancia}"


class Tema(models.Model):
    id_temas = models.AutoField(primary_key=True)
    descripcion = models.TextField()
    id_categoria = models.ForeignKey(
        Categoria, on_delete=models.CASCADE, db_column='id_categoria'
    )
    publicaciones = models.ManyToManyField(
        Publicacion, through='PublicacionTema', related_name='temas'
    )
    trends = models.ManyToManyField(
        Trend, through='TemaTrend', related_name='temas'
    )

    class Meta:
        db_table = 'Temas'

    def __str__(self):
        return f"Tema {self.id_temas}"


class PublicacionTema(models.Model):
    # Las tablas históricas usan AutoField; declararlo evita cambios de tipo espurios.
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    id_publicacion_api = models.ForeignKey(
        Publicacion, on_delete=models.CASCADE, db_column='id_publicacion_api'
    )
    id_temas = models.ForeignKey(
        Tema, on_delete=models.CASCADE, db_column='id_temas'
    )

    class Meta:
        db_table = 'Publicacion_Temas'
        unique_together = (('id_publicacion_api', 'id_temas'),)


class Etiqueta(models.Model):
    nombre = models.CharField(max_length=100)
    slug = models.SlugField(max_length=110, unique=True)

    def __str__(self):
        return self.nombre


class PublicacionEtiqueta(models.Model):
    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='etiquetas')
    etiqueta = models.ForeignKey(Etiqueta, on_delete=models.CASCADE, related_name='publicaciones')
    posicion = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['posicion', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['publicacion', 'etiqueta'], name='etiqueta_unica_por_publicacion'),
            models.UniqueConstraint(fields=['publicacion', 'posicion'], name='posicion_unica_por_publicacion'),
        ]


class TemaTrend(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    id_temas = models.ForeignKey(
        Tema, on_delete=models.CASCADE, db_column='id_temas'
    )
    id_trends = models.ForeignKey(
        Trend, on_delete=models.CASCADE, db_column='id_trends'
    )

    class Meta:
        db_table = 'Temas_Trends'
        unique_together = (('id_temas', 'id_trends'),)


class Locacion(models.Model):
    id_locacion = models.AutoField(primary_key=True)
    location = models.CharField(max_length=18)
    latitud = models.FloatField()
    longitud = models.FloatField()
    id_publicacion_api = models.ForeignKey(
        Publicacion, on_delete=models.CASCADE, db_column='id_publicacion_api'
    )

    class Meta:
        db_table = 'Locacion'


class Sentimiento(models.Model):
    id_sentimiento = models.AutoField(primary_key=True)
    polaridad = models.FloatField()
    confianza = models.FloatField()
    id_publicacion_api = models.ForeignKey(
        Publicacion, on_delete=models.CASCADE, db_column='id_publicacion_api'
    )

    def save(self, *args, **kwargs):
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        kwargs['using'] = using
        with transaction.atomic(using=using):
            publicacion = (Publicacion.objects.using(using).select_for_update()
                           .only('contenido', 'contenido_completo')
                           .get(pk=self.id_publicacion_api_id))
            if not publicacion.tiene_cuerpo_completo:
                raise ValidationError('No se puede crear un sentimiento sin cuerpo completo.')
            return super().save(*args, **kwargs)

    class Meta:
        db_table = 'Sentimiento'


class VotoPublicacion(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    id_user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column='id_user'
    )
    id_publicacion_api = models.ForeignKey(
        Publicacion, on_delete=models.CASCADE, db_column='id_publicacion_api'
    )
    tipo_voto = models.CharField(max_length=50)
    fecha_voto = models.DateTimeField()

    class Meta:
        db_table = 'Votos_Publicacion'
        unique_together = (('id_user', 'id_publicacion_api'),)


class Auditoria(models.Model):
    id_auditoria = models.AutoField(primary_key=True)
    descripcion = models.TextField()
    fecha_revision = models.DateTimeField()
    estado_aprobacion = models.CharField(max_length=2)
    id_publicacion_api = models.ForeignKey(
        Publicacion, on_delete=models.CASCADE, db_column='id_publicacion_api'
    )
    usuarios = models.ManyToManyField(
        User, through='UserAuditoria', related_name='auditorias'
    )

    class Meta:
        db_table = 'Auditoria'


class UserAuditoria(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    id_user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column='id_user'
    )
    id_auditoria = models.ForeignKey(
        Auditoria, on_delete=models.CASCADE, db_column='id_auditoria'
    )

    class Meta:
        db_table = 'User_Auditoria'
        unique_together = (('id_user', 'id_auditoria'),)


class Comentario(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente de revisión'
        PUBLICADO = 'publicado', 'Publicado'
        RECHAZADO = 'rechazado', 'Rechazado'

    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='comentarios_noticias')
    texto = models.TextField(max_length=2000)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_edicion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_creacion', '-pk']

    def __str__(self):
        return f'Comentario #{self.pk} de la publicación #{self.publicacion_id}'


class ValoracionPublicacion(models.Model):
    class Sentimiento(models.TextChoices):
        POSITIVO = 'positivo', 'Positivo'
        NEUTRAL = 'neutral', 'Neutral'
        NEGATIVO = 'negativo', 'Negativo'

    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='valoraciones')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='valoraciones_noticias')
    sentimiento = models.CharField(max_length=8, choices=Sentimiento.choices)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['publicacion', 'usuario'], name='valoracion_unica_usuario_noticia'),
            models.CheckConstraint(condition=models.Q(sentimiento__in=['positivo', 'neutral', 'negativo']), name='valoracion_sentimiento_valido'),
        ]

    def __str__(self):
        return f'{self.get_sentimiento_display()} en publicación #{self.publicacion_id}'


class SentimientoComentario(models.Model):
    """Análisis automático de sentimiento sobre un comentario.

    Independiente del modelo Sentimiento (sentimiento del texto de las noticias)
    y de ValoracionPublicacion (voto manual del lector). Se guarda una sola fila
    por comentario: al reanalizar se actualiza la misma fila, sin historial de
    versiones. texto_hash permite detectar que el comentario cambió y requiere
    reproceso; el método y el modelo utilizados quedan registrados para no
    presentar la predicción como una verdad objetiva.
    """
    class Metodo(models.TextChoices):
        LEXICON = 'lexicon', 'Léxico determinista'
        IA = 'ia', 'Modelo de IA'

    class Estado(models.TextChoices):
        PROCESADO = 'procesado', 'Procesado'
        ERROR = 'error', 'Error'

    comentario = models.OneToOneField(Comentario, on_delete=models.CASCADE, related_name='sentimiento')
    # polaridad y confianza quedan en null cuando el estado es error.
    polaridad = models.FloatField(null=True, blank=True)
    confianza = models.FloatField(null=True, blank=True)
    metodo = models.CharField(max_length=16, choices=Metodo.choices)
    # Identificador versionado del analizador (p. ej. "lexicon_v1" u "ollama:llama3.1:latest").
    modelo = models.CharField(max_length=80)
    # SHA-256 hexadecimal del texto efectivamente analizado; cambia si el comentario se edita.
    texto_hash = models.CharField(max_length=64)
    # Una de las 12 categorías del proyecto (clasificacion.CATEGORIAS_PROYECTO), la misma
    # tabla que usan las noticias; null si el analizador no pudo determinarla.
    categoria = models.ForeignKey(
        Categoria, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sentimientos_comentarios',
    )
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.PROCESADO)
    # En estado error explica el fallo; en un resultado procesado por el léxico,
    # "ia:<código>" indica que se pidió IA y falló (el comando puede reintentarlo).
    codigo_error = models.CharField(max_length=64, blank=True, default='')
    fecha_analisis = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Fuera de rango el resultado no se puede presentar; null se admite para errores.
            models.CheckConstraint(
                condition=models.Q(polaridad__isnull=True) | (
                    models.Q(polaridad__gte=-1) & models.Q(polaridad__lte=1)
                ),
                name='sentcom_polaridad_rango',
            ),
            models.CheckConstraint(
                condition=models.Q(confianza__isnull=True) | (
                    models.Q(confianza__gte=0) & models.Q(confianza__lte=1)
                ),
                name='sentcom_confianza_rango',
            ),
            # Un comentario en error no debería exponer una polaridad "sin significado".
            models.CheckConstraint(
                condition=(
                    models.Q(estado='procesado', polaridad__isnull=False, confianza__isnull=False)
                    | models.Q(estado='error')
                ),
                name='sentcom_procesado_requiere_valores',
            ),
        ]
        indexes = [
            models.Index(fields=['estado', 'fecha_actualizacion'], name='sentcom_estado_fecha_idx'),
        ]

    def __str__(self):
        if self.estado == self.Estado.ERROR:
            return f'Sentimiento del comentario #{self.comentario_id}: error ({self.codigo_error or "sin código"})'
        return f'Sentimiento del comentario #{self.comentario_id}: pol={self.polaridad}'

    @property
    def etiqueta(self):
        """Positivo, neutral o negativo para presentar; None si está en error."""
        if self.estado != self.Estado.PROCESADO or self.polaridad is None:
            return None
        if self.polaridad > 0.05:
            return 'positivo'
        if self.polaridad < -0.05:
            return 'negativo'
        return 'neutral'
