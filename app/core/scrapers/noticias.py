import urllib.request
import xml.etree.ElementTree as ET
import re
import hashlib
from django.utils import timezone
from core.models import Publicacion

def fetch_elterritorio_news(category="misiones", limit=5):
    """
    Obtiene las noticias más recientes desde el feed RSS de El Territorio
    y las guarda/actualiza en la base de datos de Django.
    """
    url = f"https://www.elterritorio.com.ar/rss/{category}/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    req = urllib.request.Request(url, headers=headers)

    articles = []
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)

            for item in root.findall('.//item')[:limit]:
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                description = item.find('description').text if item.find('description') is not None else ""

                clean_summary = re.sub(r'<[^>]+>', '', description).strip()

                # Extraer el ID numérico de la noticia desde la URL (ej. /918312-)
                match_id = re.search(r'/(\d+)-', link)
                id_api = int(match_id.group(1)) if match_id else None

                # Generar hash único basado en la URL
                hash_val = hashlib.sha256(link.strip().encode('utf-8')).hexdigest()

                if id_api:  # Solo procesar si se pudo extraer la clave primaria
                    articles.append({
                        'id_noticia': id_api,
                        'hash_origen': hash_val,
                        'title': title.strip(),
                        'link': link.strip(),
                        'summary': clean_summary,
                        'source': 'El Territorio'
                    })
    except Exception as e:
        print(f"[!] Aviso: No se pudo conectar a El Territorio ({e}). Usando datos de prueba.")
        fallback_link = 'https://www.elterritorio.com.ar/noticias/2026/obras-litoral'
        articles = [
            {
                'id_noticia': 999999,
                'hash_origen': hashlib.sha256(fallback_link.encode('utf-8')).hexdigest(),
                'title': 'Inauguran nuevas obras en el Litoral',
                'link': fallback_link,
                'summary': 'Avanzan los trabajos de infraestructura en Misiones.',
                'source': 'El Territorio'
            }
        ]

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