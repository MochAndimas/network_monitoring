"""Run from project root with backend dependencies; only reads source devices."""
import argparse
import os
from pathlib import Path

COLUMNS = ('id', 'name', 'ip_address', 'device_type', 'site', 'location', 'description', 'is_active')


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, (bool, int)):
        return str(int(value))
    # UTF-8 hex literals avoid SQL quoting and sql_mode differences.
    return "CONVERT(X'" + str(value).encode('utf-8').hex() + "' USING utf8mb4)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    from sqlalchemy import create_engine, text
    from backend.app.core.config import settings

    engine = create_engine(settings.database.url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text('SELECT ' + ', '.join(COLUMNS) + ' FROM devices ORDER BY id')).fetchall()
    finally:
        engine.dispose()
    lines = [
        '-- Devices only. Apply after Alembic migrations to a NEW, EMPTY devices table.',
        '-- Keep mysql client stop-on-error behavior; do not use --force.',
        'SET NAMES utf8mb4;',
        'START TRANSACTION;',
    ]
    # A single INSERT is atomic. No DELETE, UPDATE, REPLACE, or IGNORE.
    if rows:
        lines.append('INSERT INTO devices (' + ', '.join(COLUMNS) + ') VALUES\n' + ',\n'.join(
            '(' + ', '.join(literal(v) for v in row) + ')' for row in rows) + ';')
    lines.append('COMMIT;')
    output = Path(args.output)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print(f'Exported {len(rows)} devices to {output}. Source database was not modified.')


if __name__ == '__main__':
    main()
