from django.db import models
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


class Publicacion(models.Model):
    id_publicacion_api = models.AutoField(primary_key=True)
    hash_origen = models.CharField(max_length=64, unique=True, default="")
    fuente = models.CharField(max_length=100, default='El Territorio')  # <-- Agregado default
    titulo = models.CharField(max_length=255, default="")
    contenido = models.TextField()
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

    @property
    def imagen_publica_url(self):
        return self.imagen_archivo.url if self.imagen_archivo else self.imagen_url


class Categoria(models.Model):
    id_categoria = models.AutoField(primary_key=True)
    nombre_categoria = models.CharField(max_length=100)

    class Meta:
        db_table = 'Categorias'

    def __str__(self):
        return self.nombre_categoria


class Trend(models.Model):
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
    id_publicacion_api = models.ForeignKey(
        Publicacion, on_delete=models.CASCADE, db_column='id_publicacion_api'
    )
    id_temas = models.ForeignKey(
        Tema, on_delete=models.CASCADE, db_column='id_temas'
    )

    class Meta:
        db_table = 'Publicacion_Temas'
        unique_together = (('id_publicacion_api', 'id_temas'),)


class TemaTrend(models.Model):
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
    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='comentarios_noticias')
    texto = models.TextField(max_length=2000)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_edicion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_creacion', '-pk']

    def __str__(self):
        return f'Comentario #{self.pk} de la publicación #{self.publicacion_id}'

    @property
    def sentimiento_vigente(self):
        """Resultado visible sólo si corresponde al texto actual del comentario."""
        from .services.sentimiento_comentarios import calcular_texto_hash

        sentimiento = getattr(self, 'sentimiento', None)
        if (sentimiento is not None
                and sentimiento.estado == SentimientoComentario.Estado.PROCESADO
                and sentimiento.texto_hash == calcular_texto_hash(self.texto)):
            return sentimiento
        return None


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
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.PROCESADO)
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
