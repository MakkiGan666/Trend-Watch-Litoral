"""Política de producción sin Django, red ni lectura de archivos de secretos."""
import ipaddress
import re
from pathlib import Path


def production_config(env):
    def required(name):
        value = env.get(name, '').strip()
        if not value:
            raise ValueError(f'Producción exige {name}.')
        return value

    if required('DEBUG').lower() != 'false':
        raise ValueError('Producción exige DEBUG=False explícito.')
    secret = required('SECRET_KEY')
    if (len(secret) < 50 or len(set(secret)) < 5
            or secret.startswith('django-insecure-')
            or any(word in secret.lower() for word in ('change-me', 'changeme', 'cambiar', 'replace-me'))):
        raise ValueError('SECRET_KEY de producción inadecuada; generar una clave aleatoria propia.')
    hosts = required('ALLOWED_HOSTS').split(',')
    hosts = [host.strip() for host in hosts]
    for host in hosts:
        if not host or host.lower() == 'localhost':
            raise ValueError('ALLOWED_HOSTS exige hosts específicos de producción.')
        try:
            ipaddress.ip_address(host[1:-1] if host.startswith('[') and host.endswith(']') else host)
        except ValueError:
            if len(host) > 253 or not re.fullmatch(
                r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*', host
            ):
                raise ValueError('ALLOWED_HOSTS inválido: sin comodines, esquemas, puertos ni sufijos abiertos.')
        else:
            # Django requiere corchetes para un literal IPv6 en ALLOWED_HOSTS.
            if ':' in host and not host.startswith('['):
                raise ValueError('Usar corchetes para hosts IPv6.')
    db = {name: required('DB_' + name) for name in ('HOST', 'NAME', 'USER', 'PASSWORD', 'PORT')}
    if not db['PORT'].isascii() or not db['PORT'].isdecimal() or not 1 <= int(db['PORT']) <= 65535:
        raise ValueError('DB_PORT debe estar entre 1 y 65535.')
    sslmode = required('DB_SSLMODE')
    if sslmode not in ('disable', 'require', 'verify-ca', 'verify-full'):
        raise ValueError('DB_SSLMODE debe ser una decisión explícita de transporte PostgreSQL.')
    options = {'sslmode': sslmode}
    if sslmode in ('verify-ca', 'verify-full'):
        options['sslrootcert'] = required('DB_SSLROOTCERT')
    proxy = env.get('TRUST_PROXY_HTTPS', 'false').strip().lower()
    if proxy not in ('true', 'false'):
        raise ValueError('TRUST_PROXY_HTTPS debe ser true o false.')
    hsts = env.get('SECURE_HSTS_SECONDS', '0').strip()
    if not hsts.isascii() or not hsts.isdecimal() or not 0 <= int(hsts) <= 31536000:
        raise ValueError('SECURE_HSTS_SECONDS inválido (0 a 31536000).')
    media = Path(required('MEDIA_ROOT'))
    if not media.is_absolute():
        raise ValueError('MEDIA_ROOT debe ser una ruta absoluta de almacenamiento persistente.')
    return {
        'DEBUG': False, 'SECRET_KEY': secret, 'ALLOWED_HOSTS': hosts,
        'DATABASES': {'default': {
            'ENGINE': 'django.db.backends.postgresql',
            **{key: db[key] for key in ('HOST', 'NAME', 'USER', 'PASSWORD', 'PORT')},
            'OPTIONS': options,
        }},
        'SESSION_COOKIE_SECURE': True, 'CSRF_COOKIE_SECURE': True,
        'SESSION_COOKIE_HTTPONLY': True, 'SESSION_COOKIE_SAMESITE': 'Lax',
        'CSRF_COOKIE_SAMESITE': 'Lax', 'CSRF_TRUSTED_ORIGINS': [],
        'SECURE_SSL_REDIRECT': True,
        'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https') if proxy == 'true' else None,
        'USE_X_FORWARDED_HOST': False,
        'SECURE_HSTS_SECONDS': int(hsts),
        'SECURE_HSTS_INCLUDE_SUBDOMAINS': False, 'SECURE_HSTS_PRELOAD': False,
        'SECURE_CONTENT_TYPE_NOSNIFF': True,
        'STATIC_URL': '/static/', 'MEDIA_URL': '/media/', 'MEDIA_ROOT': media,
    }
