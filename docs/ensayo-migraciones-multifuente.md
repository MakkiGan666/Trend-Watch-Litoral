# H4.2-B — Ensayo de migraciones y restauración

Fecha: 2026-11-05. Base: `1115664d6fa111bed44c6abe0e1d92ff7198145d`.
Rama: `feat/h4-2-ensayo-migraciones`; árbol inicialmente limpio.

## Resultado

**Ensayo aprobado en PostgreSQL efímero; no autoriza despliegue ni activación.**
Se aplicaron las migraciones reales hasta 0019 para construir una base nueva,
luego 0020 y 0021. No se sustituyeron por syncdb ni se usó `--fake`.
Las nuevas migraciones sólo crearon alias y cola IA; los históricos se conservaron.
Backup `pg_dump -Fc` y restauración `pg_restore --single-transaction --exit-on-error`
completados en una segunda instancia aislada, sobre una base creada desde template0.

| Verificación | Evidencia observada |
| --- | --- |
| Aislamiento | Dos contenedores creados para el ensayo: `tw-h42b-origen` y `tw-h42b-restaurado`; NetworkMode=none, sin puertos, PGDATA en tmpfs. Clientes sólo comparten el namespace de la instancia elegida. |
| Herramientas | PostgreSQL 17.5, UTF8; imagen local `postgis/postgis:17-3.5`, cliente Django en `trendwatch-litoral-web:latest`, con `--pull never`. |
| Configuración | Ajustes sólo en /tmp; dotenv desactivado, clave sintética, Gemini vacío; conexión explícita a loopback y usuario/base sintéticos. Código montado sólo lectura. |
| Históricos | 6 publicaciones, IDs 1001–1006 y hashes SHA-256 distintos; URLs repetidas exactamente y equivalentes por tracking dentro de un medio; otra fuente y El Territorio. |
| Relaciones | 1 RegistroDatos, categoría, tema y etiqueta; 6 relaciones tema/publicación, 6 etiquetas/publicación, 6 sentimientos y 6 ubicaciones; usuario, comentario y guardado sintéticos. |
| Conservación | Conteos y hashes de todas las filas históricas iguales antes/después; secuencias históricas conservadas salvo la de django_migrations, que avanzó por las dos migraciones. Sin rehash, fusión ni eliminación de duplicados. |
| Estado inicial nuevo | Alias y cola vacíos inmediatamente después de migrar: no se encolaron ni modificaron históricos automáticamente. |
| Restricciones nuevas | 5 restricciones validadas: PK alias, UNIQUE(fuente, URL), FK alias, PK/FK cola; 4 índices: PK/UNIQUE, índice FK alias y PK cola. FK diferidas verificadas explícitamente al probar errores. |
| Columnas | Preflight H4.1 aprobado en origen y restauración: nombres, tipos, longitudes, nulabilidad, auto-ID y restricciones. token_intento admite NULL al crear pendientes. |
| Pruebas negativas | Rechazados alias duplicado, FK alias inexistente, PK cola repetida, FK cola inexistente y fuente NULL. |
| Aislamiento SQL | Read Committed observado; dos sesiones comprobaron exclusión y liberación del advisory lock por commit y rollback. H3.1 rechazó Repeatable Read antes de escribir. |
| Backup/restauración | Coinciden 34 tablas públicas por conteo y SHA-256 de filas JSON ordenadas, y 32 secuencias por valor, incluyendo registro de migraciones. |
| Esquema | Dumps de esquema completo coinciden salvo una representación equivalente de casts en CHECK histórico de valoraciones, comprobada con NULL, tres valores válidos, vacío e inválido. |
| Django check | Sin incidencias con ajustes sintéticos sobre la instancia restaurada. |

Tras comprobar las tablas nuevas vacías se insertaron **manualmente y sólo para el
ensayo** un alias y dos trabajos: PENDIENTE e INCIERTO con token/envío sintéticos.
Esos datos prueban la conservación de cola/alias en backup. No hubo llamadas IA
ni uso de servicios de ingesta. Las relaciones históricas previas permanecieron intactas.

## Fallos y recuperación ensayados

1. **Bloqueo de Publicacion durante 0020:** otra sesión mantuvo ACCESS EXCLUSIVE;
   lock_timeout=300ms produjo SQLSTATE 55P03. Se liberó el bloqueo y se descartó
   la conexión Django abortada, creando una nueva (equivalente a relanzar el worker).
   La instantánea volvió a coincidir con la línea de base: sin tabla parcial ni
   registro falso de 0020. El reintento aplicó sólo 0020 correctamente.
2. **Tabla incompatible antes de 0021:** una tabla de obstrucción vacía creada por
   el arnés produjo 42P07. 0020 permaneció aplicada, 0021 no quedó registrada.
   Se retiró exclusivamente esa obstrucción sintética y el reintento aplicó 0021.
   En destino real, detener e investigar: nunca trasladar automáticamente ese DROP
   a una tabla existente ni usar --fake para saltar la incompatibilidad.
3. **Error en transacción DML:** se insertaron alias y cola, y se lanzó una excepción.
   Ambos se revirtieron; las secuencias pueden avanzar pese al rollback (nextval no
   es transaccional). Los huecos de IDs no son pérdida de publicaciones.
4. **Restauración sobre base PostGIS preinicializada:** pg_restore abortó por schema
   tiger existente. La restauración se ejecutó en transacción única. La recuperación
   fue crear otra base vacía desde template0, sin borrar esquemas preexistentes,
   y restaurar allí con éxito. No usar --clean sobre bases ajenas al ensayo.

El arnés temporal necesitó corregir una referencia a `Publicaciones` por el nombre
real `Publicacion`, normalizar listas de secuencias al comparar JSON y excluir el
avance esperado de django_migrations de la conservación histórica. Estas correcciones
sólo afectaron /tmp; el código, modelos y migraciones del repositorio no se modificaron.

## Integridad del artefacto

- Backup temporal: `/tmp/tw-h42b-ensayo/backup.dump`, 109284 bytes.
- SHA-256 del backup: `3beb6f38e8930467c0affd21516e5ec1526e2c61bd1ee334f99bf0e9a0a75f37`.
- SHA-256 del esquema, normalizando únicamente el CHECK descrito: `e69ddc0154a29270a60b47921f473d26776f99df0bdbfd3ffb5f4e0c7bc287f7`.

Las instantáneas baseline.json/after.json, results.json, summary.json y los dos
dumps de esquema quedan en ese directorio temporal; contienen sólo datos sintéticos.
Al finalizar se detuvieron ambos contenedores; `--rm` eliminó las instancias y
sus datos en tmpfs. Sólo permanece la evidencia temporal y este informe.
El backup no incluye roles globales: el mismo rol sintético se provisionó en ambas
instancias. No se ha ensayado aquí la restauración de usuarios/permisos productivos.

## Comandos para repetir exclusivamente en un entorno desechable

Requieren las dos imágenes ya locales y el repositorio en esta revisión. No usar
Compose, .env, volúmenes habituales ni conexión a otra base. Guardar los dos bloques
Python del apéndice en un directorio temporal nuevo como ensayo_settings.py y
ensayo.py; no ejecutarlos contra una instancia existente.

```bash
ENSAYO_DIR=$(mktemp -d /tmp/tw-h42b-repeticion.XXXXXX)
APP_REPO="$PWD/app"
# Guardar aquí los archivos del apéndice, en "$ENSAYO_DIR".
docker run --pull never --rm -d --name tw-h42b-origen --network none \
  --tmpfs /var/lib/postgresql/data -v "$ENSAYO_DIR:/evidence" \
  -e POSTGRES_PASSWORD=h42b-disposable-only -e POSTGRES_USER=h42b_ephemeral \
  -e POSTGRES_DB=h42b_synthetic postgis/postgis:17-3.5
docker run --pull never --rm -d --name tw-h42b-restaurado --network none \
  --tmpfs /var/lib/postgresql/data -v "$ENSAYO_DIR:/evidence:ro" \
  -e POSTGRES_PASSWORD=h42b-disposable-only -e POSTGRES_USER=h42b_ephemeral \
  -e POSTGRES_DB=h42b_synthetic postgis/postgis:17-3.5
docker inspect --format '{{.Name}} {{.HostConfig.NetworkMode}} {{json .HostConfig.PortBindings}} {{json .HostConfig.Tmpfs}}' tw-h42b-origen tw-h42b-restaurado
docker exec tw-h42b-origen pg_isready -U h42b_ephemeral -d h42b_synthetic
docker exec tw-h42b-restaurado pg_isready -U h42b_ephemeral -d h42b_synthetic
# No continuar hasta que ambos estén listos y el aislamiento coincida.
cliente() {
  docker run --pull never --rm --network "container:$1" --read-only --tmpfs /tmp \
    -e PYTHONDONTWRITEBYTECODE=1 -e PYTHON_DOTENV_DISABLED=1 \
    -e SECRET_KEY=h42b-synthetic-settings-only -e DB_HOST= -e GEMINI_API_KEY= \
    -e H42B_DB="$2" -e PYTHONPATH=/app:/evidence \
    -v "$APP_REPO:/app:ro" -v "$ENSAYO_DIR:/evidence" \
    --entrypoint python trendwatch-litoral-web:latest -B /evidence/ensayo.py "$3"
}
cliente tw-h42b-origen h42b_synthetic prepare
cliente tw-h42b-origen h42b_synthetic migrate
cliente tw-h42b-origen h42b_synthetic locks
docker exec tw-h42b-origen pg_dump -U h42b_ephemeral -d h42b_synthetic \
  --format=custom --file=/evidence/backup.dump
sha256sum "$ENSAYO_DIR/backup.dump"
docker exec tw-h42b-restaurado createdb -U h42b_ephemeral --template=template0 h42b_restored
docker exec tw-h42b-restaurado pg_restore -U h42b_ephemeral -d h42b_restored \
  --exit-on-error --single-transaction /evidence/backup.dump
cliente tw-h42b-restaurado h42b_restored verify_restore
docker exec tw-h42b-origen pg_dump -U h42b_ephemeral -d h42b_synthetic \
  --schema-only --no-owner --no-privileges --file=/evidence/source-schema.sql
docker exec tw-h42b-restaurado pg_dump -U h42b_ephemeral -d h42b_restored \
  --schema-only --no-owner --no-privileges > "$ENSAYO_DIR/restored-schema.sql"
diff -u "$ENSAYO_DIR/source-schema.sql" "$ENSAYO_DIR/restored-schema.sql"
# Una diferencia nueva requiere revisión; no ignorar bloques indiscriminadamente.
cliente tw-h42b-restaurado h42b_restored check_schema
# Django check: mismo cliente/configuración, cambiando entrypoint de script por
# /app/manage.py check --settings=ensayo_settings y H42B_DB=h42b_restored.
docker stop tw-h42b-origen tw-h42b-restaurado
# --rm elimina ambos contenedores y su PGDATA efímero; el directorio de evidencia queda.
```

## Limitaciones y puertas de despliegue pendientes

- Este ensayo usa pocos datos y rol PostgreSQL sintético con privilegios amplios;
  no acredita tiempos con volumen real, recursos, roles mínimos, permisos, RLS,
  replicación, recuperación PITR, TLS a una base remota ni versiones diferentes.
- La migración desde cero hasta 0019 se ensayó sin datos previos; los históricos
  sintéticos se introdujeron en 0019. No prueba transformaciones históricas anteriores.
- No hubo terminación forzada del servidor, disco lleno ni corrupción física del
  backup. Los fallos ensayados fueron bloqueo, colisión DDL y rollback DML.
- No se revirtió 0020/0021 hacia 0019: esa reversión elimina alias y cola. La recuperación
  ensayada fue rollback transaccional/reintento y restauración en destino vacío.
  Una recuperación productiva debe conciliar escrituras y envíos IA posteriores al backup.
- Persisten las puertas de H4.2-A: validar cada medio con autorización separada,
  coordinar consumidor global de Gemini y pendientes inciertos, revisar conflictos
  históricos, roles y Read Committed en conexiones reales, acordar RPO/RTO y backup
  verificado del destino antes de cualquier ventana de migración. Ninguna fuente se activó.
- Código, modelos, migraciones y configuración de aplicación intactos; sin HTTP,
  Internet, Gemini, ingestas, base habitual, commits, push, merge ni PR.

## Apéndice: arnés temporal reproducible

Las credenciales siguientes son exclusivamente sintéticas, creadas para contenedores
sin red externa. No reemplazar por secretos ni apuntar a una base existente.

### ensayo_settings.py

```python
from mi_proyecto.settings import *
SECRET_KEY = 'h42b-synthetic-settings-only'
GEMINI_API_KEY = ''
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': __import__('os').environ.get('H42B_DB', 'h42b_synthetic'), 'USER': 'h42b_ephemeral', 'PASSWORD': 'h42b-disposable-only', 'HOST': '127.0.0.1', 'PORT': '5432', 'CONN_MAX_AGE': 0}}
```

### ensayo.py

```python
import os, json, hashlib, sys
from pathlib import Path
os.environ['DJANGO_SETTINGS_MODULE']='ensayo_settings'
import django
django.setup()
from django.db import connection, connections, transaction, DatabaseError, IntegrityError
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
ROOT=Path('/evidence')

def migrate(number):
    ex=MigrationExecutor(connection)
    target=('core', number)
    plan=[f'{m.app_label}.{m.name}' for m,back in ex.migration_plan([target])]
    ex.migrate([target])
    return plan

def snapshot():
    result={}
    with connection.cursor() as c:
        c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        for (name,) in c.fetchall():
            c.execute('SELECT row_to_json(t)::text FROM '+connection.ops.quote_name(name)+' t')
            rows=sorted(json.dumps(json.loads(row[0]),sort_keys=True,ensure_ascii=False) for row in c.fetchall())
            result[name]={'count':len(rows),'sha256':hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
        c.execute('SELECT sequencename,last_value FROM pg_sequences WHERE schemaname=\'public\' ORDER BY sequencename')
        result['__sequences__']=[list(row) for row in c.fetchall()]
    return result

def save(name,data):
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n')

def check_historic(before, after):
    for table,value in before.items():
        if table not in ('django_migrations','__sequences__'):
            assert after[table]==value,(table,after[table],value)
    afterseq=dict(after['__sequences__'])
    for name,value in before['__sequences__']:
        if name=='django_migrations_id_seq': continue
        assert afterseq[name]==value,(name,value,afterseq[name])

def negative(label,fn):
    try:
        with transaction.atomic():
            fn()
            connection.check_constraints()
    except IntegrityError:
        return label
    raise AssertionError('Se aceptó '+label)

mode=sys.argv[1]
if mode=='prepare':
    plan=migrate('0019_etiquetas_publicacion')
    apps=MigrationExecutor(connection).loader.project_state([('core','0019_etiquetas_publicacion')]).apps
    def M(name):return apps.get_model('core',name)
    reg=M('RegistroDatos').objects.create(fuentes_api='Histórico sintético',fecha_ejecucion=timezone.now(),estado='EXITO',lenguaje='es')
    categoria=M('Categoria').objects.create(nombre_categoria='Educación sintética')
    tema=M('Tema').objects.create(descripcion='Proyecto de escuelas sintético',id_categoria=categoria)
    etiqueta=M('Etiqueta').objects.create(nombre='Escuelas',slug='escuelas-sinteticas')
    pubs=[]
    urls=['https://misionesonline.net/ensayo/', 'https://misionesonline.net/ensayo/?utm_source=sintetico', 'https://misionesonline.net/ensayo/', 'https://www.primeraedicion.com.ar/ensayo/', 'https://www.elterritorio.com.ar/ensayo/', 'https://www.elterritorio.com.ar/ensayo/']
    for i,url in enumerate(urls):
        pub=M('Publicacion').objects.create(id_publicacion_api=1001+i,hash_origen=hashlib.sha256(f'historico-{i}'.encode()).hexdigest(),fuente=('Misiones Online' if i<3 else 'Primera Edición' if i==3 else 'El Territorio'),titulo=f'Noticia histórica sintética {i}',contenido='Texto sintético de una publicación histórica, sin conexión a fuentes reales. '*4,url=url,fecha_publicacion=timezone.now(),id_registro=reg,procesado_ia=i%2==0)
        pubs.append(pub)
        M('PublicacionTema').objects.create(id_publicacion_api=pub,id_temas=tema)
        M('PublicacionEtiqueta').objects.create(publicacion=pub,etiqueta=etiqueta,posicion=1)
        M('Sentimiento').objects.create(id_publicacion_api=pub,polaridad=0.2,confianza=0.8)
        M('Locacion').objects.create(id_publicacion_api=pub,location='Posadas',latitud=-27.37,longitud=-55.89)
    User=apps.get_model('auth','User')
    user=User.objects.create(username='usuario_sintetico',password='!')
    M('PublicacionGuardada').objects.create(publicacion=pubs[0],usuario=user)
    M('Comentario').objects.create(publicacion=pubs[0],autor=user,texto='Comentario sintético',estado='APROBADO')
    with connection.cursor() as c:
        c.execute('SELECT setval(pg_get_serial_sequence(\'"Publicacion"\', \'id_publicacion_api\'), 1006, true)')
    save('baseline.json',snapshot())
    save('preparation.json',{'plan':plan,'publicaciones':6,'ids':[p.pk for p in pubs]})
    print('0019 y datos sintéticos preparados')
elif mode=='finish_prepare':
    with connection.cursor() as c:
        c.execute('SELECT setval(pg_get_serial_sequence(\'"Publicacion"\', \'id_publicacion_api\'), 1006, true)')
    save('baseline.json',snapshot())
    print('Baseline guardada; arnés corregido para tabla Publicacion')
elif mode in ('migrate','finish_migrate'):
    before=json.loads((ROOT/'baseline.json').read_text())
    plan20=['core.0020_aliasurlpublicacion'];plan21=['core.0021_procesamientoiamultifuente']
    if mode=='migrate':
        # Falla controlada 0020: lock exclusivo de otra sesión, con timeout corto.
        import psycopg2
        peer=psycopg2.connect(dbname='h42b_synthetic',user='h42b_ephemeral',password='h42b-disposable-only',host='127.0.0.1')
        with peer.cursor() as c:c.execute('LOCK TABLE "Publicacion" IN ACCESS EXCLUSIVE MODE')
        with connection.cursor() as c:c.execute("SET lock_timeout='300ms'")
        try:
            migrate('0020_aliasurlpublicacion')
            raise AssertionError('No falló por lock')
        except DatabaseError as exc:
            assert getattr(exc.__cause__,'pgcode',None)=='55P03',repr(exc)
        finally:
            peer.rollback();peer.close()
            from django.db.backends.postgresql.base import DatabaseWrapper
            config = dict(connection.settings_dict)
            connection.close()
            connections['default'] = DatabaseWrapper(config, alias='default')  # Worker nuevo.
        assert snapshot()==before
        plan20=migrate('0020_aliasurlpublicacion')
        # Falla 0021: tabla incompatible creada sólo en este esquema de ensayo.
        with connection.cursor() as c:c.execute('CREATE TABLE core_procesamientoiamultifuente (obstruccion integer)')
        try:
            migrate('0021_procesamientoiamultifuente')
            raise AssertionError('No falló la colisión DDL')
        except DatabaseError as exc:
            assert getattr(exc.__cause__,'pgcode',None)=='42P07',repr(exc)
        with connection.cursor() as c:
            c.execute("SELECT count(*) FROM django_migrations WHERE app='core' AND name='0021_procesamientoiamultifuente'")
            assert c.fetchone()[0]==0
            c.execute('DROP TABLE core_procesamientoiamultifuente')
        plan21=migrate('0021_procesamientoiamultifuente')
    from core.services.orquestador_multifuente import verificar_esquema_multifuente
    verificar_esquema_multifuente()
    after=snapshot();check_historic(before,after)
    from core.models import AliasURLPublicacion as A, ProcesamientoIAMultifuente as Q
    assert A.objects.count()==Q.objects.count()==0
    # Datos de prueba de alias/cola: no son una ingesta ni llaman servicios.
    alias=A.objects.create(publicacion_id=1001,fuente='misiones_online',url_normalizada='https://misionesonline.net/ensayo/')
    Q.objects.create(publicacion_id=1001)
    from uuid import UUID
    Q.objects.create(publicacion_id=1002,estado='INCIERTO',token_intento=UUID(int=1),enviado=timezone.now(),codigo_error='ensayo_sin_llamada')
    rejects=[]
    rejects.append(negative('alias duplicado',lambda:A.objects.create(publicacion_id=1002,fuente=alias.fuente,url_normalizada=alias.url_normalizada)))
    rejects.append(negative('FK alias inexistente',lambda:A.objects.create(publicacion_id=999999,fuente='misiones_online',url_normalizada='https://misionesonline.net/inexistente/')))
    rejects.append(negative('PK cola duplicada',lambda:Q.objects.create(publicacion_id=1001)))
    rejects.append(negative('FK cola inexistente',lambda:Q.objects.create(publicacion_id=999999)))
    rejects.append(negative('alias fuente NULL',lambda:A.objects.create(publicacion_id=1003,fuente=None,url_normalizada='https://misionesonline.net/nulo/')))
    # Rollback de DML, incluidas relaciones, en una transacción explícita.
    state=snapshot()
    try:
        with transaction.atomic():
            A.objects.create(publicacion_id=1003,fuente='misiones_online',url_normalizada='https://misionesonline.net/rollback/')
            Q.objects.create(publicacion_id=1003)
            raise RuntimeError('corte controlado')
    except RuntimeError:pass
    now=snapshot()
    # PostgreSQL no revierte nextval: los datos sí deben permanecer iguales.
    assert {k:v for k,v in state.items() if k!='__sequences__'}=={k:v for k,v in now.items() if k!='__sequences__'}
    check_historic(before,now)
    with connection.cursor() as c:
        c.execute('SHOW transaction_isolation');isolation=c.fetchone()[0]
        assert isolation=='read committed'
        c.execute('SELECT pg_advisory_xact_lock(42424242)')
        c.execute('SELECT pg_try_advisory_xact_lock(42424242)');assert c.fetchone()[0]
        c.execute("SELECT version(), current_setting('server_encoding')");version=c.fetchone()
        c.execute("SELECT conname,contype,convalidated,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN ('core_aliasurlpublicacion'::regclass,'core_procesamientoiamultifuente'::regclass) ORDER BY conname")
        constraints=c.fetchall()
        c.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE tablename IN ('core_aliasurlpublicacion','core_procesamientoiamultifuente') ORDER BY indexname")
        indexes=c.fetchall()
    save('after.json',snapshot())
    save('results.json',{'plan20':plan20,'plan21':plan21,'isolation':isolation,'version':version,'negative_tests':rejects,'constraints':constraints,'indexes':indexes,'faults':['55P03 lock timeout 0020: rollback completo y retry correcto','42P07 tabla incompatible 0021: sin registro falso, retiro controlado y retry correcto','DML fallido: rollback de alias y cola, nextval no transaccional']})
    print('0020/0021 aplicadas; históricos intactos, preflight y restricciones correctos')
elif mode=='verify_restore':
    expected=json.loads((ROOT/'after.json').read_text())
    actual=json.loads(json.dumps(snapshot()))
    assert actual==expected,{k:(expected.get(k),actual.get(k)) for k in actual if actual.get(k)!=expected.get(k)}
    from core.services.orquestador_multifuente import verificar_esquema_multifuente
    verificar_esquema_multifuente()
    print('RESTORE OK: todas las tablas, hashes de filas, conteos y secuencias coinciden; preflight correcto')
elif mode=='check_schema':
    import re
    formulas=[]
    for filename in ('source-schema.sql','restored-schema.sql'):
        line=next(x for x in (ROOT/filename).read_text().splitlines() if 'CONSTRAINT valoracion_sentimiento_valido CHECK' in x)
        formula=line.split(' CHECK (',1)[1][:-1]
        formulas.append(formula)
    with connection.cursor() as c:
        for value in (None,'positivo','neutral','negativo','otro',''):
            outputs=[]
            for formula in formulas:
                c.execute('SELECT '+formula+' FROM (SELECT %s::varchar AS sentimiento) v',[value])
                outputs.append(c.fetchone()[0])
            assert outputs[0]==outputs[1],(value,outputs)
    print('CHECK histórico: ambas representaciones aceptan/rechazan los mismos valores, incluidos NULL e inválidos')
elif mode=='locks':
    import psycopg2
    config=dict(dbname='h42b_synthetic',user='h42b_ephemeral',password='h42b-disposable-only',host='127.0.0.1')
    a=psycopg2.connect(**config);b=psycopg2.connect(**config);b.autocommit=True
    try:
        for terminar in ('commit','rollback'):
            with a.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(42424243)')
            with b.cursor() as c:
                c.execute('SELECT pg_try_advisory_xact_lock(42424243)');assert c.fetchone()[0] is False
            getattr(a,terminar)()
            with b.cursor() as c:
                c.execute('SELECT pg_try_advisory_xact_lock(42424243)');assert c.fetchone()[0] is True
    finally:a.close();b.close()
    from core.services.persistencia_multifuente import _bloquear_fuente
    from core.services.fuentes_rss import FUENTES_RSS
    try:
        with transaction.atomic():
            with connection.cursor() as c:c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            _bloquear_fuente(FUENTES_RSS[0])
        raise AssertionError('Aceptó aislamiento incorrecto')
    except ValueError as exc:assert 'Read Committed' in str(exc)
    print('LOCKS OK: competidor bloqueado, liberación por commit y rollback; Repeatable Read rechazado sin escrituras')
else:raise ValueError(mode)
```
