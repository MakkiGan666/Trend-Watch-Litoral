"""Contrato estático deliberadamente estricto; no carga .env ni necesita Docker."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def validate(text):
    db, web = text.split('  db:\n', 1)[1].split('  web:\n', 1)
    if re.findall(r'^      DB_HOST: (.+)$', web, re.M) != ['db']:
        raise ValueError('DB_HOST debe ser db')
    if re.findall(r'^      DB_PORT: (.+)$', web, re.M) != ['5432']:
        raise ValueError('DB_PORT debe ser 5432')
    if re.findall(r'^      - "(127\.0\.0\.1:\d+:\d+)"$', db, re.M) != [
        '127.0.0.1:5433:5432'
    ]:
        raise ValueError('Publicación al anfitrión inesperada')


class PortContract(unittest.TestCase):
    def test_current_compose(self):
        validate((ROOT / 'docker-compose.yml').read_text())

    def test_reject_host_port_in_web(self):
        text = (ROOT / 'docker-compose.yml').read_text()
        with self.assertRaises(ValueError):
            validate(text.replace('DB_PORT: 5432', 'DB_PORT: 5433'))


if __name__ == '__main__':
    unittest.main()
