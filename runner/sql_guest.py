"""SQL candidate: only SELECT against an in-memory fixture, no filesystem APIs."""
import json
import sqlite3
import sys
import time

payload = json.load(sys.stdin)
connection = sqlite3.connect(':memory:')
connection.enable_load_extension(False)
# Fixtures are authored data, yet also get the authorizer: no ATTACH/PRAGMA/files.
denied = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}


def authorize(action, first, second, database, trigger):
    if action in denied or (action == sqlite3.SQLITE_FUNCTION and (second or first or '').lower() in
                           {'load_extension', 'readfile', 'writefile'}):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


connection.set_authorizer(authorize)
deadline = time.monotonic() + payload.get('time_limit_seconds', 2)
connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
connection.executescript(payload.get('setup', ''))
connection.set_authorizer(lambda action, a, b, db, trigger:
                         sqlite3.SQLITE_OK if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                         sqlite3.SQLITE_RECURSIVE, sqlite3.SQLITE_FUNCTION} and authorize(action, a, b, db, trigger) == sqlite3.SQLITE_OK
                         else sqlite3.SQLITE_DENY)
try:
    cursor = connection.execute(payload['source'])
    rows = cursor.fetchmany(1001)
except sqlite3.OperationalError as error:
    if str(error) == 'interrupted':
        sys.exit(124)
    raise
if len(rows) > 1000:
    raise ValueError('row_limit')
print(json.dumps(rows, ensure_ascii=True, allow_nan=False))
