from django.db import models
from django.utils import timezone


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
    url = models.URLField(default="")
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