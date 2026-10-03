import hashlib
import re
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime
from django.utils import timezone
from core.models import Publicacion, RegistroDatos

try:
    from newspaper import Article # pyright: ignore[reportMissingImports]
except ModuleNotFoundError:
    try:
        from newspaper3k import Article # pyright: ignore[reportMissingImports]
    except ModuleNotFoundError:
        class Article:
            def __init__(self, *args, **kwargs):
                self.text = ""

            def download(self):
                return None

            def parse(self):
                return None

REDES_SOCIALES = {
    "linktree": "https://linktr.ee/elterritoriooficial",
    "instagram": "https://www.instagram.com/elterritoriooficial/",
    "facebook": "https://www.facebook.com/elterritoriooficial/",
    "twitter": "https://twitter.com/elterritorio",
    "tiktok": "https://www.tiktok.com/@elterritoriooficial"
}

CATEGORIAS_TERRITORIO = {
    "misiones": "https://www.elterritorio.com.ar/rss/misiones",
    "tecnologia": "https://www.elterritorio.com.ar/rss/tecnologia",
    "policiales": "https://www.elterritorio.com.ar/rss/policiales",
    "cultura": "https://www.elterritorio.com.ar/rss/cultura",
    "actualidad": "https://www.elterritorio.com.ar/rss/actualidad"
}

def generar_hash(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()

def fetch_and_store_elterritorio(category="misiones", limit=10):
    url_feed = CATEGORIAS_TERRITORIO.get(category, CATEGORIAS_TERRITORIO["misiones"])
    fuente_nombre = f"El Territorio ({category.capitalize()})"
    
    # 1. Crear RegistroDatos (Auditoría de Ingesta)
    registro = RegistroDatos.objects.create(
        fuentes_api=fuente_nombre,
        fecha_ejecucion=timezone.now(),
        estado="EN_PROCESO",
        lenguaje="es"
    )
    
    volumen_capturado = 0
    
    try:
        req = urllib.request.Request(url_feed, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')[:limit]

        for item in items:
            link_node = item.find('link')
            title_node = item.find('title')
            description_node = item.find('description')

            link = link_node.text.strip() if link_node is not None and link_node.text else ""
            titulo = title_node.text.strip() if title_node is not None and title_node.text else ""
            if not link:
                continue

            hash_id = generar_hash(link)

            # 2. Deduplicación mediante ORM Django (RF-02)
            if Publicacion.objects.filter(hash_origen=hash_id).exists():
                continue # Si ya existe, omitir

            # 3. Scraping con newspaper3k para cuerpo completo
            try:
                article = Article(link, language='es')
                article.download()
                article.parse()
                description_text = description_node.text if description_node is not None and description_node.text else ""
                contenido = article.text if article.text else description_text
            except Exception:
                raw_desc = description_node.text if description_node is not None and description_node.text else ""
                contenido = re.sub(r'<[^>]+>', '', raw_desc).strip()

            # 4. Guardar en tabla Publicacion
            Publicacion.objects.create(
                hash_origen=hash_id,
                fuente=fuente_nombre,
                titulo=titulo,
                contenido=contenido,
                url=link,
                procesado_ia=False,
                id_registro=registro, # Relación ForeignKey con RegistroDatos
                fecha_captura=timezone.now()
            )
            volumen_capturado += 1

        # Actualizar estado del registro a ÉXITO
        registro.estado = "EXITO"
        registro.save()
        
        return {
            "status": "EXITO", 
            "capturados": volumen_capturado, 
            "registro_id": registro.id_registro
        }

    except Exception as e:
        registro.estado = f"ERROR: {str(e)[:40]}"
        registro.save()
        return {"status": "ERROR", "detalle": str(e)}