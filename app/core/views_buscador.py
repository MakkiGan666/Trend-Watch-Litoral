from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .fechas import datos_fecha
from .services.buscador import EntradaInvalida, TAMANO, buscar, extracto


@require_GET
def buscar_publicaciones(request):
    try:
        consulta, terminos, pagina = buscar(request.GET.get('q'), request.GET.get('page', '1'))
    except EntradaInvalida as error:
        return JsonResponse({'error': {'codigo': error.codigo, 'mensaje': str(error)}}, status=400)

    def enlace(numero):
        parametros = request.GET.copy()
        parametros['q'] = consulta
        parametros['page'] = numero
        return reverse('buscar_publicaciones') + '?' + parametros.urlencode()

    resultados = []
    for publicacion in pagina.object_list:
        resultados.append({
            'id_publicacion_api': publicacion.pk,
            'titulo': publicacion.titulo,
            'fuente': publicacion.fuente,
            **datos_fecha(publicacion),
            'detalle_url': reverse('noticia', kwargs={'pk': publicacion.pk}),
            'imagen_url': publicacion.imagen_publica_url or None,
            'extracto': extracto(publicacion.contenido, terminos),
        })
    return JsonResponse({
        'consulta': consulta, 'total': pagina.paginator.count,
        'pagina': pagina.number, 'tamano_pagina': TAMANO,
        'total_paginas': pagina.paginator.num_pages,
        'anterior': enlace(pagina.previous_page_number()) if pagina.has_previous() else None,
        'siguiente': enlace(pagina.next_page_number()) if pagina.has_next() else None,
        'resultados': resultados,
    })
