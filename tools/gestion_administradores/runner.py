import os, sys
sys.path.insert(0, '/app')
os.environ.update(SECRET_KEY='isolated-test-key-longer-than-32-characters', DB_HOST='127.0.0.1', DB_NAME=os.environ.get('TW_DATABASE', 'pr34_upgrade'), DB_USER='postgres', DB_PASSWORD='', DB_PORT='5432', DJANGO_SETTINGS_MODULE='mi_proyecto.settings')
import django
django.setup()
from django.conf import settings
settings.DATABASES['default']['TEST']['NAME']=os.environ.get('TW_TEST_DATABASE', 'test_gestion')
settings.ALLOWED_HOSTS=['testserver', 'localhost']
if os.environ.get('TW_FAST_HASH') == '1':
    settings.PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']
from django.core.management import execute_from_command_line
if sys.argv[1:] == ['scenario']:
    exec(compile(open('/evidence/scenario.py').read(), '/evidence/scenario.py', 'exec'))
    sys.exit(0)
execute_from_command_line(['manage.py', *sys.argv[1:]])
