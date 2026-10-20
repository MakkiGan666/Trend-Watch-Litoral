"""Lectura compatible de asociaciones; las secciones RSS no son el catálogo CAT-01."""
import re


def datos_categorias(publicacion):
    seccion = re.search(r'\(([^)]+)\)\s*$', publicacion.fuente or '')
    seccion = seccion.group(1).strip() if seccion else None
    categorias = {}
    for tema in publicacion.temas.all():
        categoria = tema.id_categoria
        # Identidad numérica real: no inventar códigos a partir de nombres históricos.
        categorias[categoria.pk] = {'id': categoria.pk, 'nombre': categoria.nombre_categoria}
    detalles = [categorias[pk] for pk in sorted(categorias)]
    nombres = list(dict.fromkeys(c['nombre'] for c in detalles))
    return {
        # Campo legacy: conservar su forma y fallback para clientes existentes.
        'categorias': nombres or ([seccion] if seccion else []),
        'categorias_detalle': detalles,
        'categorias_origen': 'asociaciones' if detalles else 'seccion' if seccion else 'sin_datos',
        'seccion_origen': seccion,
    }
