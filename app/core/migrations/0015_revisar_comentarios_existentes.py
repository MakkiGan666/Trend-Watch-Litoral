from django.db import migrations
import re
import unicodedata


EXPRESIONES_BLOQUEADAS = (
    'hijo de puta', 'hija de puta', 'puta', 'puto', 'mierda',
    'pelotudo', 'pelotuda', 'boludo', 'boluda', 'forro', 'forra',
    'concha de tu madre', 'la concha', 'verga', 'pija',
    'hay que matar a', 'maten a todos', 'maten a los', 'exterminar a',
)


def normalizar(texto):
    texto = unicodedata.normalize('NFKD', texto.casefold())
    texto = ''.join(letra for letra in texto if not unicodedata.combining(letra))
    texto = texto.translate(str.maketrans({'@': 'a', '0': 'o', '1': 'i', '3': 'e', '$': 's'}))
    return ' '.join(re.findall(r'[a-z0-9]+', texto))


def revisar_existentes(apps, schema_editor):
    Comentario = apps.get_model('core', 'Comentario')
    expresiones = tuple(f' {normalizar(valor)} ' for valor in EXPRESIONES_BLOQUEADAS)
    for comentario in Comentario.objects.filter(estado='publicado').only('id', 'texto').iterator():
        texto = f' {normalizar(comentario.texto)} '
        if any(expresion in texto for expresion in expresiones):
            Comentario.objects.filter(pk=comentario.pk).update(estado='pendiente')


class Migration(migrations.Migration):
    dependencies = [('core', '0014_comentario_moderacion')]

    operations = [migrations.RunPython(revisar_existentes, migrations.RunPython.noop)]
