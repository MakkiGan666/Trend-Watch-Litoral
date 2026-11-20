from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .fechas import datos_fecha
from .services.buscador import EntradaInvalida, TAMANO, buscar, extracto


def _versiones_originales(publicacion):
    return [{
        'id_publicacion_api': version.pk,
        'titulo': version.titulo,
        'fuente': version.fuente,
        'detalle_url': reverse('noticia', kwargs={'pk': version.pk}),
    } for version in publicacion._versiones_originales]


@require_GET
def buscar_publicaciones(request):
    try:
        consulta, terminos, pagina = buscar(
            request.GET.get('q'), request.GET.get('page', '1'), request.GET,
        )
    except EntradaInvalida as error:
        return JsonResponse({'error': {'codigo': error.codigo, 'mensaje': str(error)}}, status=400)

    def enlace(numero):
        parametros = request.GET.copy()
        parametros['q'] = consulta
        parametros['page'] = numero
        return reverse('buscar_publicaciones') + '?' + parametros.urlencode()

    resultados = []
    for publicacion in pagina.object_list:
        presentacion = publicacion._presentacion
        resultado = {
            'id_publicacion_api': publicacion.pk,
            'titulo': presentacion.titulo,
            'fuente': presentacion.fuente,
            **datos_fecha(presentacion),
            'detalle_url': reverse('noticia', kwargs={'pk': presentacion.pk}),
            'imagen_url': (presentacion.imagen_publica_url or None)
                if presentacion.tiene_cuerpo_completo else None,
            'extracto': extracto(presentacion.contenido, terminos)
                if presentacion.tiene_cuerpo_completo else '',
        }
        if publicacion._grupo_editorial_id:
            resultado['id_publicacion_presentada'] = presentacion.pk
            resultado['categorias'] = publicacion._categorias_presentacion
            resultado['representante'] = {
                'id_publicacion_api': publicacion.pk,
                'titulo': publicacion.titulo,
                'fuente': publicacion.fuente,
                'detalle_url': reverse('noticia', kwargs={'pk': publicacion.pk}),
            }
            resultado['versiones_originales'] = _versiones_originales(publicacion)
        if presentacion.pk != publicacion.pk:
            resultado['coincidencia'] = {
                'id_publicacion_api': presentacion.pk,
                'titulo': presentacion.titulo,
                'fuente': presentacion.fuente,
                'detalle_url': reverse('noticia', kwargs={'pk': presentacion.pk}),
            }
        resultados.append(resultado)
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
        consulta, terminos, pagina = buscar(raw, request.GET.get('page', '1'), request.GET)
    except EntradaInvalida as error:
        contexto.update(error=str(error), error_codigo=error.codigo, filtros=request.GET)
        return render(request, 'core/buscar.html', contexto, status=400)
    resultados = []
    for publicacion in pagina.object_list:
        presentacion = publicacion._presentacion
        fecha = datos_fecha(presentacion)
        valor_fecha = fecha['fecha_efectiva']
        presentacion_fecha = (date.fromisoformat(valor_fecha) if fecha['fecha_precision'] == 'dia'
                              else datetime.fromisoformat(valor_fecha)) if valor_fecha else None
        resultados.append({
            'titulo': segmentos_resaltados(presentacion.titulo, terminos),
            'es_ficha_rss': presentacion.contenido_completo is False,
            'extracto': (segmentos_resaltados(extracto(presentacion.contenido, terminos), terminos)
                         if presentacion.tiene_cuerpo_completo else None),
            'fuente': presentacion.fuente,
            'detalle_url': reverse('noticia', kwargs={'pk': presentacion.pk}),
            'imagen_url': (imagen_segura(presentacion.imagen_publica_url)
                           if presentacion.tiene_cuerpo_completo else None),
            'fecha': presentacion_fecha, **fecha,
            'categorias': publicacion._categorias_presentacion,
        })
        if publicacion._grupo_editorial_id:
            resultados[-1]['versiones_originales'] = _versiones_originales(publicacion)
            resultados[-1]['id_publicacion_presentada'] = presentacion.pk
            resultados[-1]['representante'] = {
                'titulo': publicacion.titulo,
                'fuente': publicacion.fuente,
                'detalle_url': reverse('noticia', kwargs={'pk': publicacion.pk}),
            }
        if presentacion.pk != publicacion.pk:
            resultados[-1]['coincidencia'] = {
                'titulo': presentacion.titulo,
                'fuente': presentacion.fuente,
                'detalle_url': reverse('noticia', kwargs={'pk': presentacion.pk}),
            }

    def enlace(numero):
        parametros = {'q': consulta, 'page': numero}
        parametros.update({clave: valor.isoformat() if hasattr(valor, 'isoformat') else valor
                           for clave, valor in pagina.filtros.items() if valor})
        return reverse('buscar_noticias') + '?' + urlencode(parametros)

    filtros_plantilla = {
        clave: valor.isoformat() if hasattr(valor, 'isoformat') else valor
        for clave, valor in pagina.filtros.items()
    }
    contexto.update(consulta=consulta, search_query=consulta, busqueda_realizada=True,
                    resultados=resultados, pagina=pagina, total=pagina.paginator.count,
                    filtros=filtros_plantilla,
                    anterior=enlace(pagina.previous_page_number()) if pagina.has_previous() else None,
                    siguiente=enlace(pagina.next_page_number()) if pagina.has_next() else None)
    return render(request, 'core/buscar.html', contexto)


@require_GET
def sugerencias_publicaciones(request):
    from .services.sugerencias import sugerir
    try:
        datos = sugerir(request.GET.get('q'), request.GET)
    except EntradaInvalida as error:
        respuesta = JsonResponse({'error': {'codigo': error.codigo, 'mensaje': str(error)}}, status=400)
        respuesta['Cache-Control'] = 'no-store'
        return respuesta
    respuesta = JsonResponse(datos)
    respuesta['Cache-Control'] = 'no-store'
    return respuesta
