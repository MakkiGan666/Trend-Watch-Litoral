from core.services.descarga_segura import descargar, validar_url
import xml.etree.ElementTree as ET
import re
import hashlib
from django.utils import timezone
from core.models import Publicacion
from core.services.scraper import CATEGORIAS_TERRITORIO

def fetch_elterritorio_news(category="misiones", limit=5):
    """
    Obtiene las noticias más recientes desde el feed RSS de El Territorio
    y las guarda/actualiza en la base de datos de Django.
    """
    if category not in CATEGORIAS_TERRITORIO or not isinstance(limit, int) or limit < 1:
        raise ValueError('Categoría o límite inválido')
    url = CATEGORIAS_TERRITORIO[category]

    articles = []
    root = ET.fromstring(descargar(url, timeout=8))
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('Documento RSS inválido')

    for item in root.findall('.//item')[:limit]:
        title = item.find('title').text if item.find('title') is not None else ""
        link = item.find('link').text if item.find('link') is not None else ""
        description = item.find('description').text if item.find('description') is not None else ""

        title, link, description = (v or '' for v in (title, link, description))
        link = link.strip()
        validar_url(link)
        clean_summary = re.sub(r'<[^>]+>', '', description).strip()

        # Extraer el ID numérico de la noticia desde la URL (ej. /918312-)
        match_id = re.search(r'/(\d+)-', link)
        id_api = int(match_id.group(1)) if match_id else None

        # Generar hash único basado en la URL
        hash_val = hashlib.sha256(link.strip().encode('utf-8')).hexdigest()

        if not title.strip() or not clean_summary:
            raise ValueError('Artículo incompleto')
        if any(len(v) > Publicacion._meta.get_field(c).max_length for c, v in (('titulo', title.strip()), ('url', link))):
            raise ValueError('Datos demasiado largos')
        if id_api:  # Solo procesar si se pudo extraer la clave primaria
            articles.append({
                'id_noticia': id_api,
                'hash_origen': hash_val,
                'title': title.strip(),
                'link': link.strip(),
                'summary': clean_summary,
                'source': 'El Territorio'
            })

    # Guardado en la base de datos de Django
    guardados = 0
    for art in articles:
        # Se busca por id_publicacion_api que es la Primary Key real del modelo
        obj, created = Publicacion.objects.get_or_create(
            id_publicacion_api=art['id_noticia'],
            defaults={
                'hash_origen': art['hash_origen'],
                'url': art['link'],
                'titulo': art['title'],
                'contenido': art['summary'],
                'fuente': art['source'],
                'fecha_captura': timezone.now(),
                'procesado_ia': False
            }
        )
        if created:
            guardados += 1

    print(f"[✔] Proceso finalizado. Noticias procesadas: {len(articles)} | Nuevas guardadas en BD: {guardados}")
    return articles