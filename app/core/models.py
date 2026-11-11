from .busqueda_texto_v1 import TextoComparableV1
from .imagenes import es_portada_generica

from django.db import models, router, transaction
from django.utils import timezone
from uuid import uuid4
from django.conf import settings


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


class PublicacionManager(models.Manager):
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
    contenido = models.TextField()
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
        permissions = [
            ('ejecutar_scraping', 'Puede ejecutar scraping'),
            ('procesar_ia', 'Puede ejecutar procesamiento IA'),
        ]

    def __str__(self):
        return self.titulo

    def save(self, *args, **kwargs):
        # Incluir pre_save/post_save en la misma transacción que el texto.
        # Así un fallo de etiquetas no deja el artículo guardado sin sincronizar.
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        kwargs['using'] = using
        with transaction.atomic(using=using):
            return super().save(*args, **kwargs)

    @property
    def etiquetas_visibles(self):
        """Etiquetas para mostrar: primero las temáticas de IA, luego las léxicas, sin repetir.

        Trabaja sobre `etiquetas.all()` para aprovechar `prefetch_related('etiquetas__etiqueta')`.
        """
        relaciones = sorted(self.etiquetas.all(), key=lambda r: (r.origen != PublicacionEtiqueta.Origen.IA, r.posicion, r.pk))
        vistas, resultado = set(), []
        for relacion in relaciones:
            if relacion.etiqueta_id not in vistas:
                vistas.add(relacion.etiqueta_id)
                resultado.append(relacion)
        return resultado

    @property
    def departamento_nombre(self):
        """Nombre del departamento identificado; '' si no hay información territorial válida."""
        from .localidades import DEPARTAMENTOS
        return next((d['nombre'] for d in DEPARTAMENTOS if d['slug'] == self.departamento), '') if self.departamento else ''

    @property
    def categoria_principal(self):
        """Primera categoría asociada (usa `prefetch_related('temas__id_categoria')` si está)."""
        temas = sorted(self.temas.all(), key=lambda t: t.pk)
        return temas[0].id_categoria.nombre_categoria if temas and temas[0].id_categoria_id else ''

    @property
    def imagen_publica_url(self):
        if self.imagen_archivo:
            return self.imagen_archivo.url
        return '' if es_portada_generica(self.imagen_url) else self.imagen_url


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
    """Asociación publicación–etiqueta con su procedencia.

    Un mismo catálogo (`Etiqueta`) sirve a dos orígenes independientes:
    - `lexico`: extracción determinista del texto (`services.etiquetas`), sin IA.
    - `ia`: etiquetas temáticas validadas a partir de una respuesta de Gemini u Ollama
      (`services.etiquetas_ia`); `ejecucion` apunta al registro de seguimiento que las produjo.
    Cada origen se sincroniza por separado: recalcular uno nunca borra el otro.
    """
    class Origen(models.TextChoices):
        LEXICO = 'lexico', 'Extracción del texto'
        IA = 'ia', 'Inteligencia artificial'

    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='etiquetas')
    etiqueta = models.ForeignKey(Etiqueta, on_delete=models.CASCADE, related_name='publicaciones')
    posicion = models.PositiveSmallIntegerField()
    origen = models.CharField(max_length=8, choices=Origen.choices, default=Origen.LEXICO)
    # Null en las asociaciones anteriores a este campo: no se inventa una fecha.
    fecha_asignacion = models.DateTimeField(null=True, blank=True)
    ejecucion = models.ForeignKey(
        'EjecucionIA', on_delete=models.SET_NULL, null=True, blank=True, related_name='etiquetas_asignadas',
    )
    # "proveedor:modelo" que generó la etiqueta; se conserva aunque falte el registro de seguimiento.
    modelo_ia = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        ordering = ['posicion', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['publicacion', 'etiqueta', 'origen'], name='etiqueta_unica_por_publicacion_origen'),
            models.UniqueConstraint(fields=['publicacion', 'origen', 'posicion'], name='posicion_unica_por_publicacion_origen'),
        ]
        indexes = [models.Index(fields=['origen', 'etiqueta'], name='pubetiq_origen_etiqueta_idx')]


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


class ConfiguracionIA(models.Model):
    """Configuración del motor de IA; una única fila (pk=1) administrada desde el panel.

    Sólo guarda preferencias del administrador. Las credenciales (GEMINI_API_KEY)
    y la dirección de Ollama siguen en variables de entorno: nunca en la base.
    Sin fila rige el valor predeterminado (Gemini con respaldo automático).
    """
    PK = 1
    PRINCIPAL_POR_DEFECTO = 'gemini'
    RESPALDO_POR_DEFECTO = True

    class Motor(models.TextChoices):
        GEMINI = 'gemini', 'Gemini'
        OLLAMA = 'ollama', 'Llama 3.1 (Ollama)'

    motor_principal = models.CharField(max_length=16, choices=Motor.choices, default=Motor.GEMINI)
    respaldo_automatico = models.BooleanField(default=True)
    # Último cambio automático de motor (informativo, para el panel).
    ultimo_respaldo_en = models.DateTimeField(null=True, blank=True)
    ultimo_respaldo_detalle = models.CharField(max_length=120, blank=True, default='')
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'configuración de IA'
        verbose_name_plural = 'configuración de IA'
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name='configuracionia_fila_unica'),
            models.CheckConstraint(
                condition=models.Q(motor_principal__in=['gemini', 'ollama']),
                name='configuracionia_motor_valido',
            ),
        ]

    def __str__(self):
        return f'Motor principal: {self.get_motor_principal_display()}'


class EjecucionIA(models.Model):
    """Historial de cada llamada a un modelo de IA (seguimiento y trazabilidad).

    Un registro por intento de proveedor: si el motor principal falla y responde el
    respaldo, quedan dos filas. Se escribe desde un único servicio
    (`core.services.ia.seguimiento`) y nunca se edita la respuesta original: el
    resultado que finalmente usa el sistema se guarda aparte en `resultado`.
    No contiene credenciales; las entradas que podrían tener datos personales
    (comentarios de usuarios) no se copian, sólo se referencia su id.
    """

    class Estado(models.TextChoices):
        EXITOSA = 'exitosa', 'Exitosa'
        FALLIDA = 'fallida', 'Fallida'
        INVALIDA = 'invalida', 'Respuesta inválida'

    class Tarea(models.TextChoices):
        ANALISIS_PUBLICACION = 'analisis_publicacion', 'Sentimiento y localidades de noticias'
        CLASIFICACION_CATEGORIAS = 'clasificacion_categorias', 'Clasificación de categorías'
        REVISION_DEPARTAMENTOS = 'revision_departamentos', 'Extracción territorial (departamentos)'
        ETIQUETADO_TEMATICO = 'etiquetado_tematico', 'Etiquetas temáticas'
        SENTIMIENTO_COMENTARIO = 'sentimiento_comentario', 'Sentimiento de comentarios'
        OTRA = 'otra', 'Otra operación'

    identificador = models.UUIDField(default=uuid4, unique=True, editable=False)
    tarea = models.CharField(max_length=40)
    proveedor = models.CharField(max_length=16)
    modelo = models.CharField(max_length=80, blank=True, default='')
    # True si respondió el motor alternativo porque el principal falló.
    respaldo = models.BooleanField(default=False)
    # Sin restricción de clave foránea: el historial sobrevive a la publicación y
    # nunca puede impedir ni romper una operación principal.
    publicacion = models.ForeignKey(
        Publicacion, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name='ejecuciones_ia',
    )
    entidad = models.CharField(max_length=20, blank=True, default='')
    entidad_id = models.PositiveBigIntegerField(null=True, blank=True)
    referencias = models.JSONField(default=list, blank=True)
    instrucciones = models.TextField(blank=True, default='')
    entrada = models.TextField(blank=True, default='')
    respuesta_original = models.TextField(blank=True, default='')
    resultado = models.JSONField(null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices)
    codigo_error = models.CharField(max_length=64, blank=True, default='')
    detalle_error = models.CharField(max_length=240, blank=True, default='')
    duracion_ms = models.PositiveIntegerField(null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-fecha', '-pk']
        verbose_name = 'ejecución de IA'
        verbose_name_plural = 'ejecuciones de IA'
        indexes = [
            models.Index(fields=['-fecha'], name='ejecia_fecha_idx'),
            models.Index(fields=['tarea', '-fecha'], name='ejecia_tarea_fecha_idx'),
            models.Index(fields=['estado', '-fecha'], name='ejecia_estado_fecha_idx'),
            models.Index(fields=['proveedor', 'modelo'], name='ejecia_proveedor_modelo_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(estado__in=['exitosa', 'fallida', 'invalida']),
                                   name='ejecucionia_estado_valido'),
        ]

    def __str__(self):
        return f'{self.get_tarea_display()} · {self.proveedor} · {self.get_estado_display()}'

    def get_tarea_display(self):
        return dict(self.Tarea.choices).get(self.tarea, self.tarea)
