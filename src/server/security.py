"""Пароли: PBKDF2-HMAC-SHA256, 600000 итераций и отдельная соль на запись.
Источник параметра: OWASP Password Storage Cheat Sheet. Пароль не журналируется.
"""
import hashlib
import secrets

ITERATIONS = 600_000


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def password_valid(password, encoded):
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 600_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return secrets.compare_digest(actual, digest)
    except (ValueError, TypeError, AttributeError):
        return False
