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
PALABRAS_COMUNES.update("""
    porque pues aunque mientras sino tampoco asimismo igualmente además
    parte partes hace hacen hacer hacía hacerse hecho hechos mucho mucha muchas poco poca
    estaba estaban estuvo están estar quien quienes manera través pese pleno plena vive partir
    fin fines era eran antes ahora allí acá todavía quizás cómo dónde cuándo tanto tanta tantas
    primer primera segundo segunda último última nuevo nueva ya mismo misma principal principales
    pasado próxima próximo serie caso casos tema temas algo nada nadie cosas cosa personas persona
    momento vez veces dentro fuera solo solamente cualquier alguna algunas algún así bien mejor
    tiene tienen tuvo tuvieron tendrá tendrán cuenta cuentan contó contar queremos nacional internacionales
    compartí compartió compartir relacionada relacionadas foto fotos video captura leer nota notas
    presentó presenta presentan informó informaron destaca destacó indicar indicó
    llevar llegó llega llegan sigue siguen único única total punto puntos cotidiana cotidiano anticipadas propuestas mantener
""".split())
VERSION_ETIQUETAS = 'extraccion-etiquetas-v2'
PALABRAS_COMUNES = {slugify(palabra) for palabra in PALABRAS_COMUNES}
PATRON = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}")
_PALABRA_PROPIA = r'[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+'
_NOMBRE_PROPIO = re.compile(rf'\b{_PALABRA_PROPIA}(?:[ \t]+{_PALABRA_PROPIA})+\b')
TITULOS_GENERICOS = {'agenda', 'agenda-cotidiana', 'territorio-fun', 'el-territorio-fun',
                     'fun-de-verano', 'el-territorio-fun-de-verano'}


def _nombres_propios(texto):
    for match in _NOMBRE_PROPIO.finditer(texto):
        nombre = []
        for palabra in match.group().split():
            if slugify(palabra) in PALABRAS_COMUNES:
                if 2 <= len(nombre) <= 4:
                    yield ' '.join(nombre)
                nombre = []
            else:
                nombre.append(palabra)
        if 2 <= len(nombre) <= 4:
            yield ' '.join(nombre)


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
    palabras_cuerpo = Counter()
    nombres_cuerpo = {}
    palabras_entrada = set()
    for match in PATRON.finditer(contenido):
        palabra = match.group()
        clave = slugify(palabra)
        if len(palabra) < 4 or clave in PALABRAS_COMUNES:
            continue
        palabras_cuerpo[clave] += 1
        nombres_cuerpo.setdefault(clave, palabra)
        if match.start() < 1000:
            palabras_entrada.add(clave)

    titulo_claves = set()
    for palabra in palabras_titulo:
        clave = slugify(palabra)
        if len(palabra) >= 4 and clave not in PALABRAS_COMUNES and clave not in titulo_claves:
            titulo_claves.add(clave)
            agregar(palabra, 3)
    for clave, frecuencia in palabras_cuerpo.items():
        if clave in titulo_claves or (clave in palabras_entrada and frecuencia >= 2):
            puntuaciones[clave] += min(3, frecuencia)
            nombres.setdefault(clave, nombres_cuerpo[clave])

    # El separador debe estar presente en el texto original. Tokenizar primero
    # uniría "Adorni. Fin" y "Tecnológicas y Trump".
    for nombre in _nombres_propios(titulo):
        agregar(nombre, 9)
    for match in re.finditer(r'(?iu)\b([a-záéíóúüñ]{4,})[ \t]+(?:de|del)[ \t]+([a-záéíóúüñ]{4,})\b', titulo):
        if slugify(match[1]) not in PALABRAS_COMUNES and slugify(match[2]) not in PALABRAS_COMUNES:
            agregar(match.group(0), 7)

    nombres_repetidos = Counter(slugify(nombre) for nombre in _nombres_propios(contenido))
    for nombre in _nombres_propios(contenido[:1000]):
        if slugify(nombre.split()[0]) in titulo_claves and nombres_repetidos[slugify(nombre)] >= 2:
            agregar(nombre, 5)

    ordenadas = sorted(puntuaciones, key=lambda clave: (-puntuaciones[clave], -len(clave.split('-')), clave))
    seleccionadas = []
    for clave in ordenadas:
        if '-' not in clave and (clave not in titulo_claves or puntuaciones[clave] < 4):
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
        limite = min(limite, 6)
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
            for nombre in _nombres_propios(contenido[:1000]):
                if slugify(nombre) not in TITULOS_GENERICOS:
                    agregar(nombre, 1)
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
    from core.models import Publicacion, PublicacionEtiqueta

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

        # Reemplazar en bloque evita colisiones al reordenar posiciones.
        vinculadas.delete()
        return guardar_etiquetas_propuestas(actual, propuestas)


def guardar_etiquetas_propuestas(publicacion, propuestas):
    """Persiste propuestas ordenadas con la fila bloqueada y sin vínculos vigentes."""
    from core.models import Etiqueta, PublicacionEtiqueta
    from core.services.procedencia_analitica import Metodo, procedencia

    if not propuestas:
        return 0
    using = publicacion._state.db
    # Orden global de slugs para evitar ciclos de bloqueo entre publicaciones.
    etiquetas = {}
    for slug, nombre in sorted(propuestas):
        etiquetas[slug], _ = Etiqueta.objects.using(using).get_or_create(
            slug=slug, defaults={'nombre': nombre},
        )
    datos_analisis = procedencia(Metodo.ETIQUETAS, VERSION_ETIQUETAS)
    relaciones = [
        PublicacionEtiqueta(
            publicacion_id=publicacion.pk, etiqueta=etiquetas[slug], posicion=posicion, **datos_analisis,
        )
        for posicion, (slug, _) in enumerate(propuestas, start=1)
    ]
    PublicacionEtiqueta.objects.using(using).bulk_create(relaciones)
    return len(relaciones)
