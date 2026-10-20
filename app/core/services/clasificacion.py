"""Clasificación de noticias ingeridas en las categorías y departamentos del proyecto.

Para reservar los tokens de Gemini (ej.: análisis de sentimiento):
- El departamento se detecta siempre en código, buscando municipios, nombres de
  departamento y referencias conocidas en el texto. Nunca se consulta a la IA.
- La categoría se resuelve con reglas (sección del medio y palabras clave) cuando el
  resultado es claro. Sólo las noticias dudosas van a Gemini, en una llamada por
  cada 20; si la IA no está disponible o responde algo inválido, quedan las reglas.
"""
import json
import logging
import re

from core.localidades import DEPARTAMENTOS, normalizar_nombre
from core.models import Categoria, PublicacionTema, Tema

logger = logging.getLogger(__name__)

# Nombres del proyecto original (docs/prototipos/LitoralPage.jsx).
CATEGORIAS_PROYECTO = [
    'Salud', 'Policiales', 'Turismo', 'Economía', 'Política', 'Educación',
    'Tecnología', 'Sociedad', 'Cultura', 'Ambiente', 'Deportes', 'Festividades',
]
CATEGORIA_POR_DEFECTO = 'Sociedad'

# Secciones del medio que corresponden directamente a una categoría propia.
# Las secciones generales (misiones, actualidad, la-region, pais-y-mundo) no
# definen categoría: se decide por el contenido.
SECCION_A_CATEGORIA = {
    'policiales': 'Policiales',
    'archivo-criminal': 'Policiales',
    'cultura': 'Cultura',
    'tecnologia': 'Tecnología',
    'deportes': 'Deportes',
    'agro': 'Economía',
    'emprender': 'Economía',
    'viajes-turismo': 'Turismo',
    'fiesta-del-inmigrante': 'Festividades',
    'elecciones': 'Política',
    'espectaculos-farandula': 'Cultura',
    'cines-y-series': 'Cultura',
    'vida-estilo': 'Sociedad',
}

# Raíces normalizadas (sin tildes, en minúscula). Se buscan como inicio de palabra.
PALABRAS_CLAVE = {
    'Salud': ['hospital', 'salud', 'medic', 'vacun', 'dengue', 'enfermedad', 'paciente',
              'sanitari', 'epidemiolog', 'cancer', 'caps'],
    'Policiales': ['polic', 'detenid', 'detuv', 'robo', 'homicidio', 'asesin', 'crimen', 'delito',
                   'fiscal', 'allanamiento', 'choque', 'siniestro vial', 'accidente',
                   'narco', 'secuestr', 'estafa', 'prision', 'juzgado', 'condena'],
    'Turismo': ['turis', 'cataratas', 'visitantes', 'hotel', 'temporada', 'parque nacional',
                'excursion', 'viaje'],
    'Economía': ['econom', 'agro', 'yerba', 'cosecha', 'productor', 'precio', 'inflacion',
                 'tarifa', 'comerci', 'emprend', 'empresa', 'export', 'salari', 'empleo',
                 'dolar', 'impuesto', 'industria', 'forestal', 'mercado', 'cooperativa'],
    'Política': ['gobernador', 'intendente', 'diputad', 'senador', 'concejo', 'legislatura',
                 'eleccion', 'candidat', 'ministr', 'gobierno', 'municipalidad', 'decreto',
                 'presidente'],
    'Educación': ['escuela', 'educa', 'docente', 'alumno', 'estudiant', 'universidad', 'unam',
                  'clases', 'colegio', 'escolar', 'maestr'],
    'Tecnología': ['tecnolog', 'digital', 'internet', 'aplicacion', 'inteligencia artificial',
                   'software', 'celular', 'ciberseguridad', 'robot'],
    'Sociedad': ['vecinos', 'barrio', 'familia', 'comunidad', 'solidari', 'clima', 'lluvia',
                 'temperatura'],
    'Cultura': ['cultura', 'musica', 'artista', 'libro', 'teatro', 'museo', 'cine', 'concierto',
                'exposicion', 'pelicula', 'escritor'],
    'Ambiente': ['ambient', 'monte nativo', 'selva', 'incendio', 'fauna', 'flora', 'yaguarete',
                 'reciclaj', 'contaminacion', 'deforest', 'sequia', 'rio parana', 'biodiversidad'],
    'Deportes': ['futbol', 'deport', 'torneo', 'campeonato', 'partido de', 'goles', 'basquet',
                 'atleta', 'club', 'seleccion', 'rugby', 'voley', 'tenis', 'maraton'],
    'Festividades': ['fiesta', 'festival', 'celebracion', 'aniversario', 'feria', 'carnaval',
                     'inmigrante', 'patronal', 'peregrinacion', 'navidad', 'desfile'],
}

# Nombres compartidos con otros lugares o palabras comunes: sólo cuentan si el
# texto los acompaña de una referencia explícita a la localidad.
_MUNICIPIOS_AMBIGUOS = {'san martin', 'san jose', 'san antonio', 'guarani', 'santa maria',
                        'san pedro', 'corpus', 'wanda', 'loreto', 'mojon grande', 'azara',
                        'puerto rico', 'santa ana', 'san ignacio', 'san vicente', 'san javier'}
_PREFIJOS_LOCALIDAD = r'(?:en|de|localidad de|municipio de|ciudad de|vecinos de)\s+'

# Referencias habituales en las notas que no son nombres de municipio.
ALIAS_DEPARTAMENTO = {
    'capital': ['capital misionera'],
    'iguazu': ['cataratas', 'parque nacional iguazu', 'triple frontera'],
    'guarani': ['mocona'],
    'sanignacio': ['ruinas de san ignacio'],
}
_MAX_NOTICIAS_POR_LLAMADA = 20
_LARGO_CONTENIDO_IA = 700
_MAX_RESPUESTA_IA = 256 * 1024
_NOMBRES_FECHA = {'9 de julio', '25 de mayo', 'dos de mayo'}
_FUERA_DE_MISIONES = re.compile(
    r'\s+(?:(?:de|en)(?: la provincia de)?\s+)?'
    r'(?:buenos aires|corrientes|cordoba|chaco|santa fe|entre rios|el salvador|estados unidos|estadounidense|caribe)(?![a-z0-9])'
)


def _texto_normalizado(*partes):
    return ' ' + normalizar_nombre(' '.join(p or '' for p in partes)) + ' '


def _contar(raiz, texto):
    return len(re.findall(r'(?<![a-z0-9])' + re.escape(normalizar_nombre(raiz)), texto))


_PESO_TITULO = 3


def categoria_con_confianza(titulo, contenido, seccion=None):
    """Clasifica sin IA y devuelve (categoria, segura).

    Es segura si la sección del medio la define, o si una palabra clave aparece en el
    título y la categoría ganadora duplica en puntaje a la segunda.
    """
    directa = SECCION_A_CATEGORIA.get((seccion or '').strip().lower())
    if directa:
        return directa, True
    titulo_n = _texto_normalizado(titulo)
    cuerpo_n = _texto_normalizado(contenido)
    puntajes = {}
    for categoria, raices in PALABRAS_CLAVE.items():
        # El título pesa más que el cuerpo: suele resumir el tema principal.
        puntaje = sum(_PESO_TITULO * _contar(r, titulo_n) + _contar(r, cuerpo_n) for r in raices)
        if puntaje:
            puntajes[categoria] = puntaje
    if not puntajes:
        return CATEGORIA_POR_DEFECTO, False
    # Empates: gana el orden de CATEGORIAS_PROYECTO para que el resultado sea estable.
    ganadora = max(CATEGORIAS_PROYECTO, key=lambda c: puntajes.get(c, 0))
    primero = puntajes[ganadora]
    segundo = max((p for c, p in puntajes.items() if c != ganadora), default=0)
    evidencia_titulo = any(_contar(raiz, titulo_n) for raiz in PALABRAS_CLAVE[ganadora])
    return ganadora, bool(evidencia_titulo and primero >= _PESO_TITULO and primero >= 2 * segundo)


def categoria_por_reglas(titulo, contenido, seccion=None):
    """Propuesta legacy sin IA; usar categoria_con_confianza antes de persistirla."""
    return categoria_con_confianza(titulo, contenido, seccion)[0]


def departamento_por_texto(titulo, contenido):
    """Busca municipios y departamentos del catálogo en el texto de la noticia.

    Devuelve el slug del departamento más mencionado, o '' si no hay menciones
    o hay empate entre departamentos distintos.
    """
    texto = _texto_normalizado(titulo, titulo, contenido)  # el título cuenta doble
    menciones = {}
    for departamento in DEPARTAMENTOS:
        nombres = {normalizar_nombre(m) for m in departamento['municipios']}
        nombres.add(normalizar_nombre(departamento['nombre']))
        nombres.update(normalizar_nombre(a) for a in ALIAS_DEPARTAMENTO.get(departamento['slug'], []))
        total = 0
        for nombre in nombres:
            if nombre == 'guarani':
                patron = (r'departamento(?: de)?\s+guarani' if departamento['slug'] == 'guarani'
                          else r'(?:en|localidad de|municipio de|ciudad de|vecinos de)\s+guarani')
            elif nombre == 'capital':
                patron = r'departamento(?: de)?\s+capital'
            elif nombre in _NOMBRES_FECHA:
                patron = r'(?:localidad de|municipio de|ciudad de)\s+' + re.escape(nombre)
            elif nombre in _MUNICIPIOS_AMBIGUOS:
                patron = _PREFIJOS_LOCALIDAD + re.escape(nombre)
            else:
                patron = re.escape(nombre)
            for coincidencia in re.finditer(r'(?<![a-z0-9])' + patron + r'(?![a-z0-9])', texto):
                # Un homónimo con jurisdicción externa explícita no prueba ubicación misionera.
                if not _FUERA_DE_MISIONES.match(texto, coincidencia.end()):
                    total += 1
        if total:
            menciones[departamento['slug']] = total
    if not menciones:
        return ''
    maximo = max(menciones.values())
    ganadores = [slug for slug, total in menciones.items() if total == maximo]
    return ganadores[0] if len(ganadores) == 1 else ''


def _prompt_clasificacion():
    return f"""
Eres el clasificador de noticias de TrendWatch Litoral (provincia de Misiones, Argentina).
Recibirás un arreglo JSON de noticias con "indice", "seccion", "titulo" y "contenido".
Para cada noticia elige exactamente UNA categoría de esta lista cerrada:
{", ".join(CATEGORIAS_PROYECTO)}.
Si la sección del medio no existe en la lista, deriva la noticia a la categoría más cercana
(ej.: agro, yerba mate o comercio -> Economía; elecciones -> Política; escuelas -> Educación).
Responde ÚNICAMENTE un arreglo JSON, un objeto por noticia, sin propiedades adicionales:
[{{"indice": int, "categoria": string}}]
"""


def _validar_respuesta(raw, indices):
    if not isinstance(raw, str) or len(raw) > _MAX_RESPUESTA_IA:
        raise ValueError('Respuesta de clasificación ausente o excesiva.')
    def sin_claves_duplicadas(pares):
        objeto = {}
        for clave, valor in pares:
            if clave in objeto:
                raise ValueError('Campo JSON repetido.')
            objeto[clave] = valor
        return objeto

    data = json.loads(raw, object_pairs_hook=sin_claves_duplicadas)
    if not isinstance(data, list):
        raise ValueError('La respuesta debe ser un arreglo.')
    resultado = {}
    for item in data:
        if not isinstance(item, dict) or set(item) != {'indice', 'categoria'}:
            raise ValueError('Cada elemento debe tener indice y categoria.')
        indice, categoria = item['indice'], item['categoria']
        if isinstance(indice, bool) or not isinstance(indice, int) or indice not in indices:
            raise ValueError('Índice inexistente.')
        if indice in resultado:
            raise ValueError('Índice repetido.')
        if categoria not in CATEGORIAS_PROYECTO:
            raise ValueError('Categoría fuera de la lista.')
        resultado[indice] = categoria
    return resultado


def _clasificar_con_ia(lote):
    """Devuelve {indice: categoria} con lo que Gemini clasificó válidamente; {} si no está disponible."""
    # Importación diferida: gemini_cliente importa el scraper, que importa este módulo.
    from core.services.gemini_cliente import gemini_cliente
    if gemini_cliente.client is None or gemini_cliente.types is None:
        return {}
    resultado = {}
    for inicio in range(0, len(lote), _MAX_NOTICIAS_POR_LLAMADA):
        parte = lote[inicio:inicio + _MAX_NOTICIAS_POR_LLAMADA]
        entrada = [
            {'indice': i, 'seccion': n.get('seccion') or '', 'titulo': n['titulo'],
             'contenido': (n.get('contenido') or '')[:_LARGO_CONTENIDO_IA]}
            for i, n in parte
        ]
        try:
            respuesta = gemini_cliente.client.models.generate_content(
                model=gemini_cliente.model_name,
                contents=json.dumps(entrada, ensure_ascii=False),
                config=gemini_cliente.types.GenerateContentConfig(
                    system_instruction=_prompt_clasificacion(),
                    response_mime_type='application/json',
                    temperature=0.1,
                ),
            )
            indices = {i for i, _ in parte}
            validas = _validar_respuesta(respuesta.text, indices)
            if set(validas) != indices:
                logger.warning('Respuesta de clasificación incompleta: %d de %d noticias.', len(validas), len(indices))
            resultado.update(validas)
        except Exception as exc:
            # Un lote rechazado no frena la ingesta: esas noticias van por reglas.
            logger.warning('Clasificación IA descartada (%s); se usan reglas locales.', type(exc).__name__)
    return resultado


def clasificar_lote(noticias, usar_ia=True):
    """Clasifica noticias {'titulo', 'contenido', 'seccion'} en el mismo orden recibido.

    Conserva categoria/departamento/metodo y agrega confirmada. La categoría de
    reglas es sólo una propuesta si confirmada=False; no debe persistirse como
    asociación automática. Una respuesta IA validada confirma su propuesta.
    """
    resultados = []
    dudosas = []
    for indice, noticia in enumerate(noticias):
        categoria, segura = categoria_con_confianza(
            noticia['titulo'], noticia.get('contenido'), noticia.get('seccion'),
        )
        resultados.append({
            'categoria': categoria,
            'departamento': departamento_por_texto(noticia['titulo'], noticia.get('contenido')),
            'metodo': 'reglas',
            'confirmada': segura,
        })
        if not segura:
            dudosas.append((indice, noticia))
    por_ia = _clasificar_con_ia(dudosas) if usar_ia and dudosas else {}
    for indice, categoria in por_ia.items():
        resultados[indice].update(categoria=categoria, metodo='ia', confirmada=True)
    return resultados


def vincular_categoria(publicacion, categoria):
    """Vincula la publicación a la categoría a través de un Tema existente o uno automático."""
    tema = Tema.objects.filter(id_categoria=categoria).first()
    if not tema:
        tema = Tema.objects.create(
            id_categoria=categoria,
            descripcion=f'Tema automático para {categoria.nombre_categoria}'
        )
    PublicacionTema.objects.get_or_create(id_publicacion_api=publicacion, id_temas=tema)


def vincular_categoria_por_nombre(publicacion, nombre):
    categoria = Categoria.objects.filter(nombre_categoria=nombre).order_by('pk').first()
    if categoria is None:
        categoria = Categoria.objects.create(nombre_categoria=nombre)
    vincular_categoria(publicacion, categoria)
