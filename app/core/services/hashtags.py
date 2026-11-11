"""Hashtags del buscador: filtros reales derivados de las publicaciones guardadas.

Tres tipos, todos calculados sobre las noticias que coinciden con la consulta:

- ``ent``: personas, lugares o instituciones. Nombres propios de los títulos:
  secuencias de palabras con mayúscula ("Passalacqua", "San Ignacio", "Parque de
  las Naciones"). Filtra por título o contenido con la normalización V1 del buscador.
- ``cat``: categorías temáticas asignadas (``Tema`` -> ``Categoria``).
- ``dep``: departamento de Misiones guardado en ``Publicacion.departamento``.

Nada está fijo en el código: un hashtag sólo aparece si filtra al menos una noticia,
y su ``total`` es exactamente la cantidad de resultados que devuelve al aplicarlo.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.db import connection
from django.db.models import Count, Q
from django.utils.text import slugify

from core.busqueda_texto_v1 import plegar_v1
from core.localidades import DEPARTAMENTOS
from core.models import Publicacion
from core.services.buscador import EntradaInvalida, condicion_terminos, publicaciones_coincidentes
from core.services.clasificacion import CATEGORIAS_PROYECTO

LIMITE = 8
LIMITE_ENTIDADES = 5
LIMITE_CATEGORIAS = 2
LIMITE_DEPARTAMENTOS = 2
# Los títulos más recientes sugieren candidatas; el conteo exacto, sobre todas
# las coincidencias, decide cuáles se muestran.
MUESTRA_TITULOS = 400
CANDIDATAS_ENTIDAD = 20
# Un hashtag relacionado debe ser al menos un 20% más frecuente en la búsqueda que
# en todo el archivo; si no, describe al archivo en general, no a la consulta.
AFINIDAD_MINIMA = 1.2
MAX_PALABRAS_ENTIDAD = 4

# Unen partes de un mismo nombre: "Parque de las Naciones", "Leandro N. Alem".
CONECTORES = frozenset({'de', 'del', 'la', 'las', 'los', 'el'})  # sin "y": separa nombres
# Palabras que pueden ir con mayúscula sin nombrar a nadie (inicio de frase, o
# genéricas dentro de nombres compuestos). Sólo se descartan como candidatas.
PALABRAS_COMUNES = frozenset('''
    el la los las lo un una uno unos unas del al con por que sus les hay mas para como desde
    entre sobre este esta esto estos estas ese esa esos esas cuando donde tras ante hasta
    segun porque pero todo toda todos todas mientras cual cuales quien quienes muy sin
    tambien ademas asi fue son ser era sera gran nuevo nueva nuevos nuevas dia dias ano anos
    hoy ayer manana ahora video videos foto fotos dos tres cada otro otra otros otras alla
    aqui ahi tu su mi nacional nacionales provincial provinciales municipal municipales
    regional federal general plan programa noche tarde semana mes fiesta encuentro
    misionero misionera misioneros misioneras
'''.split())
# Tras estos signos empieza una frase: su primera mayúscula no prueba un nombre propio.
INICIO_FRASE = frozenset(':.;!?¿¡"“”«»\'‘’|—–-')

_CATEGORIAS = {slugify(nombre): nombre for nombre in CATEGORIAS_PROYECTO}
_DEPARTAMENTOS = {d['slug']: d['nombre'] for d in DEPARTAMENTOS}
_PATRON_VALOR = re.compile(r'(ent|cat|dep):([^\s:]{1,80})')
_PATRON_ENTIDAD = re.compile(r'\w{1,40}(?:-\w{1,40}){0,%d}' % (MAX_PALABRAS_ENTIDAD - 1))
_FICHAS = re.compile(r'\w+|[^\w\s]')


def _etiqueta(nombre):
    """'San Ignacio' -> '#SanIgnacio'; conserva acentos y mayúsculas internas."""
    return '#' + ''.join(p[:1].upper() + p[1:] for p in re.findall(r'\w+', nombre))


def _mayuscula(palabra):
    return palabra[:1] != palabra[:1].lower()


@dataclass(frozen=True)
class Hashtag:
    tipo: str
    clave: str
    nombre: str

    @property
    def valor(self):
        return f'{self.tipo}:{self.clave}'

    @property
    def texto(self):
        return _etiqueta(self.nombre)

    @property
    def frase(self):
        """Texto plegado que se busca: 'parque-de-las-naciones' -> 'parque de las naciones'."""
        return self.clave.replace('-', ' ')

    @property
    def descripcion(self):
        return {'ent': 'Persona, lugar o institución', 'cat': 'Categoría',
                'dep': 'Departamento'}[self.tipo]

    def condicion(self):
        if self.tipo == 'ent':
            return Q(titulo_busqueda__contains=self.frase) | Q(contenido_busqueda__contains=self.frase)
        if self.tipo == 'cat':
            return Q(temas__id_categoria__nombre_categoria=self.nombre)
        return Q(departamento=self.clave)

    def filtrar(self, publicaciones):
        if self.tipo == 'cat':
            # Subconsulta: una noticia con varios temas no se repite en los resultados.
            ids = Publicacion.objects.filter(self.condicion()).values('pk')
            return publicaciones.filter(pk__in=ids)
        return publicaciones.filter(self.condicion())


def _entidad(palabras):
    clave = '-'.join(plegar_v1(p) for p in palabras)
    return Hashtag('ent', clave, ' '.join(palabras))


def interpretar_hashtag(valor):
    """Valor del parámetro ``h`` -> Hashtag; vacío -> None; otro caso, error 400."""
    if valor is None or valor == '':
        return None
    invalido = EntradaInvalida('hashtag_invalido', 'El filtro h no corresponde a un hashtag válido.')
    if any(unicodedata.category(c).startswith('C') for c in valor):
        raise invalido
    coincidencia = _PATRON_VALOR.fullmatch(unicodedata.normalize('NFC', valor))
    if not coincidencia:
        raise invalido
    tipo, clave = coincidencia.groups()
    if tipo == 'cat' and clave in _CATEGORIAS:
        return Hashtag('cat', clave, _CATEGORIAS[clave])
    if tipo == 'dep' and clave in _DEPARTAMENTOS:
        return Hashtag('dep', clave, _DEPARTAMENTOS[clave])
    if tipo == 'ent' and _PATRON_ENTIDAD.fullmatch(clave) and clave == plegar_v1(clave):
        partes = clave.split('-')
        if len(clave) >= 3 and not all(p.isdigit() for p in partes):
            return _entidad([p.capitalize() if p not in CONECTORES else p for p in partes])
    raise invalido


def nombres_propios(titulo):
    """Secuencias de palabras con mayúscula de un título, sin la palabra inicial de frase."""
    fichas = _FICHAS.findall(unicodedata.normalize('NFC', titulo or ''))
    nombres, actual, inicio_frase, actual_inicia_frase = [], [], True, False

    def agregar(partes):
        while partes and plegar_v1(partes[0]) in PALABRAS_COMUNES | CONECTORES:
            partes = partes[1:]
        while partes and plegar_v1(partes[-1]) in CONECTORES:
            partes = partes[:-1]
        if len(partes) == 1 and (plegar_v1(partes[0]) in PALABRAS_COMUNES or len(partes[0]) < 3
                                 or partes[0].isdigit()):
            return
        if partes:
            nombres.append(partes)

    def cerrar():
        partes = list(actual)
        while partes and plegar_v1(partes[-1]) in CONECTORES:
            partes.pop()
        # Al comenzar una frase, una sola palabra con mayúscula no prueba nada.
        if actual_inicia_frase and len(partes) == 1:
            return
        # Nombres largos se cortan antes de un conector: "Parque de las Naciones" + "Oberá".
        while len(partes) > MAX_PALABRAS_ENTIDAD:
            corte = max(i for i in range(1, MAX_PALABRAS_ENTIDAD + 1)
                        if plegar_v1(partes[i - 1]) not in CONECTORES)
            agregar(partes[:corte])
            partes = partes[corte:]
        agregar(partes)

    for ficha in fichas:
        if not ficha[0].isalnum() and ficha[0] != '_':
            if actual:
                cerrar()
                actual = []
            inicio_frase = ficha in INICIO_FRASE or inicio_frase
            continue
        if _mayuscula(ficha) and not ficha.isdigit():
            if not actual:
                actual_inicia_frase = inicio_frase
            actual.append(ficha)
        elif actual and plegar_v1(ficha) in CONECTORES:
            actual.append(ficha)
        elif actual:
            cerrar()
            actual = []
        inicio_frase = False
    if actual:
        cerrar()
    return nombres


def _candidatas_entidad(publicaciones):
    """Una consulta: títulos recientes; los nombres más repetidos pasan al conteo exacto."""
    frecuencia, formas, minusculas = Counter(), defaultdict(Counter), Counter()
    for titulo in publicaciones.values_list('titulo', flat=True)[:MUESTRA_TITULOS]:
        minusculas.update({plegar_v1(f) for f in _FICHAS.findall(titulo or '') if f.islower()})
        vistos = set()
        for palabras in nombres_propios(titulo):
            hashtag = _entidad(palabras)
            if hashtag.clave in vistos:
                continue
            vistos.add(hashtag.clave)
            frecuencia[hashtag.clave] += 1
            formas[hashtag.clave][hashtag.nombre] += 1

    def forma_preferida(clave):
        # La grafía más usada; "Posadas" antes que "POSADAS" si ambas aparecen.
        return max(formas[clave].items(), key=lambda f: (f[0] != f[0].upper(), f[1], f[0]))[0]

    # Una palabra suelta que en los mismos títulos va en minúscula al menos tantas
    # veces como con mayúscula es común ("El Niño" / "un niño"): como filtro de
    # contenido coincidiría con cualquier uso, así que no se ofrece.
    comunes = {clave for clave in frecuencia if '-' not in clave and minusculas[clave] >= frecuencia[clave]}
    ordenadas = sorted((c for c in frecuencia if c not in comunes), key=lambda clave: (-frecuencia[clave], clave))
    return [Hashtag('ent', clave, forma_preferida(clave)) for clave in ordenadas[:CANDIDATAS_ENTIDAD]]


def hashtags_de_busqueda(terminos, seleccionado=None):
    """Hashtags contextuales de una consulta, con conteos exactos.

    Cuatro consultas: títulos de muestra, conteos dentro de la búsqueda (el
    ``total`` de cada hashtag es lo que devuelve el buscador al aplicarlo),
    frecuencias en todo el archivo y categorías. El orden premia la afinidad: lo
    que es más frecuente en esta búsqueda que en el archivo completo. El hashtag
    que coincide con la propia consulta va primero.
    """
    publicaciones = publicaciones_coincidentes(terminos)
    frase_consulta = ' '.join(terminos)
    entidades = _candidatas_entidad(publicaciones)
    estructurados = ([Hashtag('cat', slug, nombre) for slug, nombre in _CATEGORIAS.items()]
                     + [Hashtag('dep', slug, nombre) for slug, nombre in _DEPARTAMENTOS.items()])
    todos = entidades + estructurados

    # 1) Dentro de la búsqueda: el filtro textual va una sola vez en el WHERE.
    locales = {'busqueda': Count('pk')}
    for indice, hashtag in enumerate(todos):
        if hashtag.tipo != 'cat':
            locales[f'l{indice}'] = Count('pk', filter=hashtag.condicion())
        if hashtag.tipo == 'ent':
            locales[f't{indice}'] = Count('pk', filter=Q(titulo_busqueda__contains=hashtag.frase))
    # Uso en el contenido de cada palabra suelta: " Niño" frente a " niño". LIKE
    # distingue mayúsculas en PostgreSQL; SQLite no, así que allí no se compara.
    sensible = connection.vendor == 'postgresql'
    sueltas = [(i, h) for i, h in enumerate(entidades) if '-' not in h.clave] if sensible else []
    for indice, hashtag in sueltas:
        locales[f'M{indice}'] = Count('pk', filter=Q(contenido__contains=' ' + hashtag.nombre))
        locales[f'm{indice}'] = Count('pk', filter=Q(contenido__contains=' ' + hashtag.nombre.lower()))
    conteos = publicaciones.order_by().aggregate(**locales)

    # 2) Todo el archivo, sólo columnas cortas (título y departamento): recorrer el
    #    contenido completo por cada candidata tardaba varios segundos.
    generales = {'archivo': Count('pk')}
    for indice, hashtag in enumerate(todos):
        if hashtag.tipo == 'ent':
            generales[f'g{indice}'] = Count('pk', filter=Q(titulo_busqueda__contains=hashtag.frase))
        elif hashtag.tipo == 'dep':
            generales[f'g{indice}'] = Count('pk', filter=hashtag.condicion())
    conteos.update(Publicacion.objects.order_by().aggregate(**generales))

    # 3) Categorías: una consulta agrupada; DISTINCT sólo aquí, donde la unión con
    #    temas puede repetir una publicación.
    coincide = condicion_terminos(terminos)
    por_categoria = {
        fila['temas__id_categoria__nombre_categoria']: fila
        for fila in Publicacion.objects.order_by()
        .filter(temas__id_categoria__nombre_categoria__in=list(_CATEGORIAS.values()))
        .values('temas__id_categoria__nombre_categoria')
        .annotate(local=Count('pk', filter=coincide, distinct=True), general=Count('pk', distinct=True))
    }
    for indice, hashtag in enumerate(todos):
        if hashtag.tipo == 'cat':
            fila = por_categoria.get(hashtag.nombre, {'local': 0, 'general': 0})
            conteos[f'l{indice}'], conteos[f'g{indice}'] = fila['local'], fila['general']

    comunes = {hashtag.valor for indice, hashtag in sueltas
               if conteos[f'm{indice}'] > conteos[f'M{indice}']}
    en_busqueda, en_archivo = conteos['busqueda'], conteos['archivo']
    minimo = 2 if en_busqueda >= 10 else 1

    def afinidad(indice, hashtag):
        # Entidades: se comparan títulos con títulos, la misma base en ambos lados.
        local = conteos[f't{indice}'] if hashtag.tipo == 'ent' else conteos[f'l{indice}']
        general = conteos[f'g{indice}']
        return (local / en_busqueda) / (general / en_archivo) if local and general else 0

    puntuados = []
    for indice, hashtag in enumerate(todos):
        local = conteos[f'l{indice}']
        if hashtag.valor in comunes or not local:
            continue
        exacto = plegar_v1(hashtag.nombre) == frase_consulta
        relacion = afinidad(indice, hashtag)
        if exacto:
            puntaje = math.inf
        elif local >= minimo and relacion > AFINIDAD_MINIMA:
            puntaje = local * math.log(relacion)
        else:
            continue
        puntuados.append((hashtag, local, puntaje))

    def mejores(tipo, limite):
        filas = [fila for fila in puntuados if fila[0].tipo == tipo]
        return sorted(filas, key=lambda fila: (-fila[2], -fila[1], fila[0].clave))[:limite]

    estructurados = mejores('cat', LIMITE_CATEGORIAS) + mejores('dep', LIMITE_DEPARTAMENTOS)
    # Sin duplicados visibles: "#Oberá" o "#Política" estructurados reemplazan al nombre suelto.
    nombres = {plegar_v1(h.nombre) for h, _, _ in estructurados}
    entidades = [fila for fila in mejores('ent', LIMITE_ENTIDADES) if fila[0].frase not in nombres]
    elegidos = sorted(entidades + estructurados, key=lambda fila: (-fila[2], -fila[1]))[:LIMITE]
    elegidos = [(h, n) for h, n, _ in elegidos]
    if seleccionado is not None and all(h.valor != seleccionado.valor for h, _ in elegidos):
        # El filtro activo siempre se muestra, para poder quitarlo. Si ya fue
        # contado se reutiliza su grafía ("Passalacqua", no "passalacqua").
        indice = next((i for i, h in enumerate(todos) if h.valor == seleccionado.valor), None)
        previo = ((todos[indice], conteos[f'l{indice}']) if indice is not None
                  else (seleccionado, seleccionado.filtrar(publicaciones).count()))
        elegidos = [previo, *elegidos[:LIMITE - 1]]
    return [{'valor': h.valor, 'texto': h.texto, 'tipo': h.tipo, 'descripcion': h.descripcion,
             'total': n, 'seleccionado': seleccionado is not None and h.valor == seleccionado.valor}
            for h, n in elegidos]
