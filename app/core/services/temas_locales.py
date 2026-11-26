"""Evidencia temática por familias léxicas y expresiones completas."""

import re

from core.localidades import normalizar_nombre

VERSION_CLASIFICACION_LOCAL = 'clasificacion-reglas-v3'
_PALABRA = re.compile(r'[a-z0-9]+')

# Cada grupo es una sola evidencia. Flexiones y sinónimos cercanos no inflan
# el puntaje. Los nombres de instituciones y los prefijos abiertos se omiten.
_FAMILIAS = {
    'Salud': (
        'hospital hospitales', 'medico medica medicos medicas', 'paciente pacientes',
        'sanitaria sanitario sanitarias sanitarios', 'enfermedad enfermedades', 'enfermero enfermera enfermeros enfermeras',
        'vacuna vacunas vacunacion', 'dengue cancer', 'tratamiento tratamientos', 'cirugia cirugias', 'pediatra pediatras pediatria',
        'salud', 'internacion internado internada', 'menopausia climaterio',
    ),
    'Policiales': (
        'policia policial policiales policias', 'detenido detenida detencion detenidos', 'robo robos asalto asaltos',
        'homicidio homicidios homicida', 'crimen criminal delito delitos', 'allanamiento allanamientos',
        'choque choques colision vuelco', 'siniestro accidentes accidente', 'estafa estafas',
        'prision carcel', 'imputado imputada acusado acusada', 'femicidio femicidios', 'electrocutado electrocutada electrocucion',
        'investigacion pesquisas',
    ),
    'Turismo': (
        'turismo turistico turistica turisticos turisticas turistas turista', 'cataratas', 'visitante visitantes',
        'hotel hoteles hoteleria hotelero hotelera hoteleras', 'excursion excursiones', 'reservas reserva',
        'ocupacion pernocte', 'temporada', 'alojamiento alojamientos',
    ),
    'Economía': (
        'economia economico economica economicos economicas', 'agro agricola agricolas horticola horticolas',
        'yerba yerbatera', 'cosecha cosechas', 'productor productores productoras', 'precio precios',
        'inflacion inflacionaria', 'tarifa tarifas', 'comercio comercios comercial', 'emprendimiento emprendimientos emprendedores',
        'empresa empresas empresarios empresarial', 'exportacion exportaciones', 'salario salarios sueldo sueldos',
        'empleo empleos desempleo', 'dolar dolares', 'impuesto impuestos', 'mercado mercados', 'consumo consumidores',
        'carniceria carnicerias', 'ventas venta', 'inversion inversiones', 'presupuesto presupuestos',
    ),
    'Política': (
        'gobernador gobernadora gobernadores', 'intendente intendenta intendentes', 'diputado diputada diputados diputadas',
        'senado senador senadora senadores', 'concejo concejales', 'legislatura legislativo legislativa',
        'eleccion elecciones electoral electorales', 'candidato candidata candidatos', 'ministro ministra ministros',
        'gobierno gobiernos', 'municipalidad municipios municipio', 'decreto decretos', 'presidente presidencia presidencial',
        'congreso bancada', 'oficialismo oposicion', 'vocero voceria', 'ordenanza ordenanzas',
    ),
    'Educación': (
        'escuela escuelas escolar escolares', 'educacion educativo educativa educativos educativas',
        'docente docentes educadores', 'alumno alumnos estudiante estudiantes', 'universidad universidades universitario universitaria',
        'clase clases', 'colegio colegios', 'rector rectores rectorado', 'curricula curricular', 'becas beca',
    ),
    'Tecnología': (
        'tecnologia tecnologias tecnologico tecnologica tecnologicas tecnologicos', 'digital digitales digitalizacion',
        'internet conectividad', 'software programacion', 'aplicacion aplicaciones', 'celular celulares',
        'ciberseguridad ciberataque', 'robot robots robotica', 'algoritmo algoritmos', 'computacion informatica',
    ),
    'Sociedad': (
        'vecinal vecinos vecinas', 'barrio barrios', 'familia familias familiar familiares',
        'comunidad comunidades comunitario comunitaria', 'solidario solidaria solidaridad', 'voluntario voluntarios voluntariado',
        'vivienda viviendas', 'barrial barriales',
    ),
    'Cultura': (
        'cultura culturales cultural', 'musica musical musicales', 'artista artistas artistico artistica arte',
        'libro libros lectora lector lecturas lectura', 'teatro teatral teatros', 'museo museos',
        'cine pelicula peliculas audiovisual audiovisuales', 'concierto conciertos recital recitales reci',
        'exposicion exposiciones', 'escritor escritora escritores', 'cartelera espectaculo espectaculos',
        'chamame chamamecera chamamecero', 'banda bandas', 'biblioteca bibliotecas', 'coreografia coreografico',
    ),
    'Ambiente': (
        'ambiente ambiental ambientales', 'selva monte', 'incendio incendios', 'fauna flora', 'yaguarete yaguaretes',
        'reciclaje reciclado', 'contaminacion contaminante', 'deforestacion desmonte', 'sequia',
        'biodiversidad ecosistema ecosistemas', 'conservacion', 'sostenibilidad sustentabilidad', 'humedal humedales',
    ),
    'Deportes': (
        'futbol futbolista futbolistas', 'deporte deportes deportivo deportiva', 'torneo torneos campeonato campeonatos',
        'partido partidos', 'gol goles goleada', 'basquet basquetbol baloncesto', 'atleta atletas atletismo',
        'rugby', 'voley voleibol', 'tenis tenista', 'maraton maratones', 'seleccion seleccionado',
        'futbolistico futbolistica', 'delantero lateral arquero', 'octavos semifinal semifinales',
    ),
    'Festividades': (
        'fiesta fiestas festejo festejos festividad festividades', 'carnaval carnavales', 'aniversario aniversarios',
        'feria ferias', 'estudiantina', 'colectividad colectividades', 'patronal patronales', 'peregrinacion peregrinaciones',
        'navidad', 'desfile desfiles carroza carrozas', 'inmigrante inmigrantes',
    ),
}

# Anclas que describen el hecho, frente a términos circunstanciales como el
# lugar del incidente o el público de un evento.
_ANCLAS = {
    'Salud': ('terapia intensiva', 'atencion primaria', 'centro de salud', 'salud publica'),
    'Policiales': ('murio electrocutado', 'murio electrocutada', 'descarga electrica', 'prision preventiva',
                   'causa de homicidio', 'siniestro vial'),
    'Turismo': ('temporada turistica', 'ocupacion hotelera', 'reservas hoteleras'),
    'Economía': ('precio de la carne', 'precios de la carne', 'consumo de carne', 'aumento de precios', 'carne vacuna'),
    'Política': ('concejo deliberante', 'casa rosada', 'campana electoral', 'reforma electoral'),
    'Educación': ('ciclo lectivo', 'financiamiento universitario', 'comunidad educativa'),
    'Tecnología': ('inteligencia artificial', 'redes neuronales', 'seguridad informatica'),
    'Sociedad': ('centro vecinal', 'colecta solidaria', 'merendero comunitario'),
    'Cultura': ('clubes de lectura', 'comunidades lectoras', 'rueda chamamecera', 'programacion de espectaculos'),
    'Ambiente': ('monte nativo', 'proteccion del yaguarete', 'conservacion ambiental'),
    'Deportes': ('torneo regional', 'liga nacional de basquet', 'copa del mundo'),
    'Festividades': ('fiesta provincial', 'fiesta nacional', 'fiesta del inmigrante', 'expo carrozas',
                     'fiesta de las colectividades'),
}

_AMBIGUAS = frozenset({
    'salud', 'investigacion pesquisas', 'temporada', 'mercado mercados', 'presupuesto presupuestos',
    'presidente presidencia presidencial', 'municipalidad municipios municipio', 'alumno alumnos estudiante estudiantes',
    'digital digitales digitalizacion', 'aplicacion aplicaciones', 'familia familias familiar familiares',
    'comunidad comunidades comunitario comunitaria', 'barrio barrios', 'artista artistas artistico artistica arte',
    'ambiente ambiental ambientales', 'selva monte', 'partido partidos', 'seleccion seleccionado',
    'aniversario aniversarios', 'feria ferias', 'inmigrante inmigrantes',
})
_INDICE = {
    palabra: (categoria, familia)
    for categoria, familias in _FAMILIAS.items()
    for familia in familias
    for palabra in familia.split()
}
_INDICE_ANCLAS = {
    tuple(frase.split()): categoria
    for categoria, frases in _ANCLAS.items()
    for frase in frases
}


def _evidencia(palabras):
    evidencias = {categoria: set() for categoria in _FAMILIAS}
    for palabra in set(palabras):
        coincidencia = _INDICE.get(palabra)
        if coincidencia:
            categoria, familia = coincidencia
            evidencias[categoria].add(familia)
    return evidencias


def _anclas(palabras):
    categorias = set()
    for indice in range(len(palabras)):
        for longitud in (2, 3, 4):
            categoria = _INDICE_ANCLAS.get(tuple(palabras[indice:indice + longitud]))
            if categoria:
                categorias.add(categoria)
    return categorias


def categoria_local_confirmada(titulo, contenido):
    """Pondera titular y entrada, con corroboración y margen ante rivales."""
    titulo = _PALABRA.findall(normalizar_nombre(titulo or ''))
    palabras = _PALABRA.findall(normalizar_nombre(contenido or ''))
    titular, entrada, resto = map(_evidencia, (titulo, palabras[:115], palabras[115:]))
    anclas_titulo = _anclas(titulo)
    anclas_entrada = _anclas(palabras[:115])
    cuerpo = {categoria: entrada[categoria] | resto[categoria] for categoria in _FAMILIAS}

    def peso(familias):
        return 2 * len(familias) - len(familias & _AMBIGUAS)

    puntajes = {
        categoria: (3 * peso(titular[categoria]) + 2 * peso(entrada[categoria])
                    + min(3, peso(resto[categoria] - entrada[categoria]))
                    + 8 * (categoria in anclas_titulo) + 5 * (categoria in anclas_entrada))
        for categoria in _FAMILIAS
    }
    orden = sorted(puntajes, key=puntajes.get, reverse=True)
    ganadora, segunda = orden[:2]
    primero, rival = puntajes[ganadora], puntajes[segunda]
    if primero < 12 or primero - rival < 5 or primero * 2 < rival * 3:
        return None

    temas_titular = titular[ganadora] - _AMBIGUAS
    temas_entrada = entrada[ganadora] - _AMBIGUAS
    familias = titular[ganadora] | cuerpo[ganadora]
    if (temas_titular or ganadora in anclas_titulo) and (
        (cuerpo[ganadora] and (len(familias) >= 2 or ganadora in anclas_titulo))
        or ganadora in anclas_entrada
    ):
        return ganadora

    # La entrada puede suplir un título genérico. Una señal fuerte de otro
    # tema en el titular exige abstención en esta ruta.
    rival_en_titular = any(
        categoria in anclas_titulo or titular[categoria] - _AMBIGUAS
        for categoria in orden[1:]
    )
    if not rival_en_titular:
        entrada_anclada = ganadora in anclas_entrada and len(temas_entrada) >= 2
        entrada_corroborada = len(temas_entrada) >= 3 and len(temas_entrada & resto[ganadora]) >= 2
        if entrada_anclada or entrada_corroborada:
            return ganadora
    return None
