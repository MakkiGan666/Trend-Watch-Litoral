from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Agrega el análisis automático de sentimiento sobre los comentarios.

    Es aditiva: crea una tabla independiente con OneToOne a core.Comentario y
    no modifica modelos existentes. Reversible mediante `migrate core 0010`.
    """

    dependencies = [
        ('core', '0010_perfilusuario_publicacionguardada'),
    ]

    operations = [
        migrations.CreateModel(
            name='SentimientoComentario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('polaridad', models.FloatField(null=True, blank=True)),
                ('confianza', models.FloatField(null=True, blank=True)),
                ('metodo', models.CharField(choices=[('lexicon', 'Léxico determinista'), ('ia', 'Modelo de IA')], max_length=16)),
                ('modelo', models.CharField(max_length=80)),
                ('texto_hash', models.CharField(max_length=64)),
                ('estado', models.CharField(choices=[('procesado', 'Procesado'), ('error', 'Error')], default='procesado', max_length=16)),
                ('codigo_error', models.CharField(blank=True, default='', max_length=64)),
                ('fecha_analisis', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('comentario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='sentimiento', to='core.comentario')),
            ],
            options={
                'constraints': [
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
                    models.CheckConstraint(
                        condition=(
                            models.Q(estado='procesado', polaridad__isnull=False, confianza__isnull=False)
                            | models.Q(estado='error')
                        ),
                        name='sentcom_procesado_requiere_valores',
                    ),
                ],
                'indexes': [
                    models.Index(fields=['estado', 'fecha_actualizacion'], name='sentcom_estado_fecha_idx'),
                ],
            },
        ),
    ]
