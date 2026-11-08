"""Etiquetas compartidas obtenidas del título y del texto, sin IA."""

import re
from collections import Counter
from html import unescape

from django.db import transaction
from django.utils.html import strip_tags
from django.utils.text import slugify

PALABRAS_COMUNES = set('''
    acerca actualmente además ahora algunos ante ayer bajo cada casi como contra cuando
    desde después donde durante ellos entre esta estas este estos fueron había hasta
    hacia hicieron hizo incluso indicó informó luego más misma mismo
    muchos para pero puede pueden señaló según será sobre también tiene todos tras
    una unas unos noticia publicación territorio fuente medio local provincia misiones
    año años día días este esta eso esa del las los por con sin sus que fue son han
    haber otra otro otras otros entre desde hasta sobre mediante una uno dos tres
'''.split())
PALABRAS_COMUNES.update({'de', 'la', 'el', 'en', 'al', 'se', 'su', 'un', 'y', 'o', 'a', 'e', 'es', 'no', 'le', 'lo', 'ya'})
PALABRAS_COMUNES.update('nuevo nueva nuevos nuevas todo toda todos todas recibió recibieron regreso nacer llevar realizó realizará anunció publicó kilos vamos estamos dispuesto dispuestos objetivo objetivos queremos dijo afirmó fun agenda on the lunes martes miércoles jueves viernes sábado domingo enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre'.split())
PALABRAS_COMUNES = {slugify(palabra) for palabra in PALABRAS_COMUNES}
PATRON = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}")
TITULOS_GENERICOS = {'agenda', 'territorio-fun', 'el-territorio-fun'}


def sugerir_etiquetas(titulo, contenido, limite=15):
    titulo = unescape(strip_tags(titulo or ''))
    contenido = unescape(strip_tags(contenido or ''))[:8000]
    puntuaciones = Counter()
    nombres = {}

    def agregar(texto, puntos):
        clave = slugify(texto)
        if not clave or len(clave) > 110:
            return
        puntuaciones[clave] += puntos
        nombres.setdefault(clave, texto.strip())
        return clave

    palabras_titulo = PATRON.findall(titulo)
    for texto, peso in ((titulo, 3), (contenido, 1)):
        for palabra in PATRON.findall(texto):
            if len(palabra) >= 4 and slugify(palabra) not in PALABRAS_COMUNES:
                agregar(palabra, peso)

    # Sólo unir nombres propios o expresiones con nexo; no mezclar palabras a ambos
    # lados de un signo de puntuación ni producir todas las parejas posibles.
    for indice in range(len(palabras_titulo) - 1):
        izquierda, derecha = palabras_titulo[indice:indice + 2]
        if (izquierda[0].isupper() and derecha[0].isupper()
                and slugify(izquierda) not in PALABRAS_COMUNES
                and slugify(derecha) not in PALABRAS_COMUNES):
            agregar(f'{izquierda} {derecha}', 9)
    for match in re.finditer(r'(?iu)\b([a-záéíóúüñ]{4,})\s+(de|del|al|para|con)\s+([a-záéíóúüñ]{4,})\b', titulo):
        if slugify(match[1]) not in PALABRAS_COMUNES and slugify(match[3]) not in PALABRAS_COMUNES:
            agregar(match.group(0), 7)

    titulo_claves = {slugify(palabra) for palabra in palabras_titulo}
    for match in re.finditer(r'\b([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)[ \t]+([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)\b', contenido):
        if (slugify(match[1]) in titulo_claves
                and slugify(match[1]) not in PALABRAS_COMUNES
                and slugify(match[2]) not in PALABRAS_COMUNES):
            agregar(match.group(0), 5)

    ordenadas = sorted(puntuaciones, key=lambda clave: (-puntuaciones[clave], -len(clave.split('-')), clave))
    seleccionadas = []
    for clave in ordenadas:
        if len(clave.split('-')) == 1 and puntuaciones[clave] < 4:
            continue
        if len(clave.split('-')) == 1 and any(
            clave in elegida.split('-') and puntuaciones[elegida] >= puntuaciones[clave]
            and all(palabra[0].isupper() for palabra in nombres[elegida].split())
            for elegida in seleccionadas if '-' in elegida
        ):
            continue
        seleccionadas.append(clave)
        if len(seleccionadas) == limite:
            break

    # En títulos genéricos o textos literarios puede no repetirse ningún término
    # del título. Sólo en esos casos usamos nombres y términos del cuerpo.
    if not seleccionadas:
        titulo_clave = slugify(titulo)
        if titulo_clave not in TITULOS_GENERICOS:
            for palabra in palabras_titulo:
                clave = slugify(palabra)
                if len(palabra) >= 5 and clave not in PALABRAS_COMUNES:
                    clave = agregar(palabra, 4)
                    if clave is None or clave in seleccionadas:
                        continue
                    seleccionadas.append(clave)
                    if len(seleccionadas) == limite:
                        break
        if len(seleccionadas) < limite:
            for match in re.finditer(r'\b([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)[ \t]+([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)\b', contenido[:1000]):
                if (slugify(match[1]) not in PALABRAS_COMUNES
                        and slugify(match[2]) not in PALABRAS_COMUNES
                        and slugify(match.group(0)) not in TITULOS_GENERICOS):
                    agregar(match.group(0), 1)
            for clave in sorted(puntuaciones, key=lambda c: (-puntuaciones[c], c)):
                if clave not in seleccionadas and len(clave.split('-')) > 1:
                    seleccionadas.append(clave)
                    if len(seleccionadas) == limite:
                        break
        if len(seleccionadas) < limite:
            for clave in sorted(puntuaciones, key=lambda c: (-puntuaciones[c], c)):
                if (clave not in seleccionadas and len(clave.split('-')) == 1
                        and puntuaciones[clave] >= 2
                        and not any(clave in nombre.split('-') for nombre in seleccionadas if '-' in nombre)):
                    seleccionadas.append(clave)
                    if len(seleccionadas) == limite:
                        break
    return [(clave, nombres[clave][:100]) for clave in seleccionadas]


def sincronizar_etiquetas(publicacion, *, using=None, solo_sin_etiquetas=False):
    """Sincroniza desde el texto persistido; nunca desde una instancia obsoleta.

    El bloqueo serializa sincronizaciones de una misma publicación en PostgreSQL.
    SQLite no ofrece bloqueo de fila; no reintentamos errores de base de datos.
    """
    from core.models import Etiqueta, Publicacion, PublicacionEtiqueta

    using = using or publicacion._state.db or 'default'
    with transaction.atomic(using=using):
        actual = (Publicacion.objects.using(using).select_for_update()
                  .only('titulo', 'contenido', 'contenido_completo').get(pk=publicacion.pk))
        vinculadas = PublicacionEtiqueta.objects.using(using).filter(publicacion_id=actual.pk)
        if not actual.tiene_cuerpo_completo:
            # Las fichas RSS no producen etiquetas inferidas. También quitamos
            # relaciones previas si una publicación se convierte explícitamente.
            vinculadas.delete()
            return 0
        if solo_sin_etiquetas and vinculadas.exists():
            return 0
        propuestas = sugerir_etiquetas(actual.titulo, actual.contenido)
        existentes = list(vinculadas.order_by('posicion').values_list('etiqueta__slug', 'posicion'))
        esperadas = [(slug, posicion) for posicion, (slug, _) in enumerate(propuestas, start=1)]
        if existentes == esperadas:
            return len(propuestas)

        # Orden global para no adquirir uniques de slugs en órdenes opuestos
        # cuando dos publicaciones comparten varias etiquetas nuevas.
        etiquetas = {}
        for slug, nombre in sorted(propuestas):
            etiquetas[slug], _ = Etiqueta.objects.using(using).get_or_create(
                slug=slug, defaults={'nombre': nombre},
            )
        # Reemplazo atómico sólo cuando cambia la secuencia. Evita colisiones
        # temporales de la restricción única de posición al intercambiar etiquetas.
        vinculadas.delete()
        relaciones = [
            PublicacionEtiqueta(publicacion_id=actual.pk, etiqueta=etiquetas[slug], posicion=posicion)
            for posicion, (slug, _) in enumerate(propuestas, start=1)
        ]
        PublicacionEtiqueta.objects.using(using).bulk_create(relaciones)
    return len(relaciones)
