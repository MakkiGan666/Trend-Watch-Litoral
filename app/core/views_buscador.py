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


@require_GET
def buscar_noticias(request):
    import unicodedata
    from datetime import date, datetime
    from urllib.parse import urlencode
    from django.shortcuts import render
    from .presentacion_busqueda import imagen_segura, segmentos_resaltados

    raw = request.GET.get('q', '')
    contexto = {'search_query': raw, 'busqueda_realizada': False}
    # Sólo el estado inicial HTML es distinto de la API obligatoria; el servicio
    # sigue siendo el único que valida y consulta una búsqueda real.
    vacia = all(c.isspace() and (not unicodedata.category(c).startswith('C') or c in '\t\r\n') for c in raw)
    if vacia:
        return render(request, 'core/buscar.html', contexto)
    try:
        consulta, terminos, pagina = buscar(raw, request.GET.get('page', '1'))
    except EntradaInvalida as error:
        contexto.update(error=str(error), error_codigo=error.codigo)
        return render(request, 'core/buscar.html', contexto, status=400)
    resultados = []
    for publicacion in pagina.object_list:
        fecha = datos_fecha(publicacion)
        valor_fecha = fecha['fecha_efectiva']
        presentacion_fecha = (date.fromisoformat(valor_fecha) if fecha['fecha_precision'] == 'dia'
                              else datetime.fromisoformat(valor_fecha)) if valor_fecha else None
        resultados.append({
            'titulo': segmentos_resaltados(publicacion.titulo, terminos),
            'extracto': segmentos_resaltados(extracto(publicacion.contenido, terminos), terminos),
            'fuente': publicacion.fuente,
            'detalle_url': reverse('noticia', kwargs={'pk': publicacion.pk}),
            'imagen_url': imagen_segura(publicacion.imagen_publica_url),
            'fecha': presentacion_fecha, **fecha,
        })

    def enlace(numero):
        return reverse('buscar_noticias') + '?' + urlencode({'q': consulta, 'page': numero})

    contexto.update(consulta=consulta, search_query=consulta, busqueda_realizada=True,
                    resultados=resultados, pagina=pagina, total=pagina.paginator.count,
                    anterior=enlace(pagina.previous_page_number()) if pagina.has_previous() else None,
                    siguiente=enlace(pagina.next_page_number()) if pagina.has_next() else None)
    return render(request, 'core/buscar.html', contexto)
