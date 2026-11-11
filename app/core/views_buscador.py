from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .fechas import datos_fecha
from .services.buscador import EntradaInvalida, TAMANO, buscar, extracto, validar_consulta
from .services.hashtags import hashtags_de_busqueda, interpretar_hashtag


@require_GET
def buscar_publicaciones(request):
    try:
        hashtag = interpretar_hashtag(request.GET.get('h'))
        consulta, terminos, pagina = buscar(request.GET.get('q'), request.GET.get('page', '1'), hashtag)
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
        hashtag = interpretar_hashtag(request.GET.get('h'))
        consulta, terminos, pagina = buscar(raw, request.GET.get('page', '1'), hashtag)
    except EntradaInvalida as error:
        contexto.update(error=str(error), error_codigo=error.codigo)
        return render(request, 'core/buscar.html', contexto, status=400)
    base_url = reverse('buscar_noticias')
    # Sin coincidencias ni filtro activo no hay nada que explorar: se evitan las consultas.
    hashtags = hashtags_de_busqueda(terminos, hashtag) if pagina.paginator.count or hashtag else []
    for etiqueta in hashtags:
        # El hashtag activo enlaza a la búsqueda sin filtro; el resto aplica el suyo.
        parametros = {'q': consulta} if etiqueta['seleccionado'] else {'q': consulta, 'h': etiqueta['valor']}
        etiqueta['url'] = base_url + '?' + urlencode(parametros)
    hashtag_activo = next((e for e in hashtags if e['seleccionado']), None)
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
        parametros = {'q': consulta, 'h': hashtag.valor, 'page': numero} if hashtag else {'q': consulta, 'page': numero}
        return base_url + '?' + urlencode(parametros)

    contexto.update(consulta=consulta, search_query=consulta, busqueda_realizada=True,
                    hashtags=hashtags, hashtag_activo=hashtag_activo,
                    sin_filtro_url=base_url + '?' + urlencode({'q': consulta}),
                    resultados=resultados, pagina=pagina, total=pagina.paginator.count,
                    anterior=enlace(pagina.previous_page_number()) if pagina.has_previous() else None,
                    siguiente=enlace(pagina.next_page_number()) if pagina.has_next() else None)
    return render(request, 'core/buscar.html', contexto)


@require_GET
def hashtags_publicaciones(request):
    """Hashtags de la consulta escrita; cada uno es un filtro aplicable con ``h``."""
    try:
        consulta, terminos = validar_consulta(request.GET.get('q'))
    except EntradaInvalida as error:
        respuesta = JsonResponse({'error': {'codigo': error.codigo, 'mensaje': str(error)}}, status=400)
        respuesta['Cache-Control'] = 'no-store'
        return respuesta
    hashtags = [{clave: etiqueta[clave] for clave in ('valor', 'texto', 'tipo', 'descripcion', 'total')}
                for etiqueta in hashtags_de_busqueda(terminos)]
    respuesta = JsonResponse({'consulta': consulta, 'hashtags': hashtags})
    respuesta['Cache-Control'] = 'no-store'
    return respuesta


@require_GET
def sugerencias_publicaciones(request):
    from .services.sugerencias import sugerir
    try:
        datos = sugerir(request.GET.get('q'))
    except EntradaInvalida as error:
        respuesta = JsonResponse({'error': {'codigo': error.codigo, 'mensaje': str(error)}}, status=400)
        respuesta['Cache-Control'] = 'no-store'
        return respuesta
    respuesta = JsonResponse(datos)
    respuesta['Cache-Control'] = 'no-store'
    return respuesta
