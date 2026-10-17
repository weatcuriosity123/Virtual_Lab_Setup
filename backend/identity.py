"""Verified Cloudflare Access identity. Configuration is off by default."""
from contextvars import ContextVar
from dataclasses import dataclass
import os
import re
from threading import Lock

import jwt
from fastapi import HTTPException

MODE = os.getenv('AUTH_MODE', 'off').lower()
ISSUER = os.getenv('CF_ACCESS_TEAM_URL', '').rstrip('/')
AUDIENCE = os.getenv('CF_ACCESS_AUD', '')
ADMIN_EMAILS = frozenset(email.strip().lower() for email in
                         os.getenv('ADMIN_EMAILS', '').split(',') if email.strip())
actor_context = ContextVar('lab_actor', default=None)
_client = None
_key_lock = Lock()


@dataclass(frozen=True)
class Actor:
    subject: str
    email: str


def validate_config():
    if MODE not in ('off', 'cloudflare'):
        raise RuntimeError('AUTH_MODE must be off or cloudflare')
    if MODE == 'cloudflare':
        if not re.fullmatch(r'https://[a-zA-Z0-9-]+\.cloudflareaccess\.com', ISSUER) or not AUDIENCE:
            raise RuntimeError('Cloudflare auth requires a valid CF_ACCESS_TEAM_URL and CF_ACCESS_AUD')


def verify(assertion):
    global _client
    if not isinstance(assertion, str) or not assertion or len(assertion) > 16384:
        raise HTTPException(401, 'Sign in through the lab portal to continue.')
    try:
        # Serialize key refreshes; network requests have a bounded timeout and
        # PyJWT caches the JWKS for key rotation. Token signatures are always checked.
        with _key_lock:
            if _client is None:
                _client = jwt.PyJWKClient(ISSUER+'/cdn-cgi/access/certs', timeout=5, lifespan=300)
            key = _client.get_signing_key_from_jwt(assertion).key
        claims = jwt.decode(assertion, key, algorithms=['RS256'], audience=AUDIENCE,
                            issuer=ISSUER, options={'require':['exp','iat','iss','aud','sub','email']})
        subject, email = claims['sub'], claims['email']
        if not isinstance(subject,str) or not subject or not isinstance(email,str):
            raise jwt.InvalidTokenError()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email)>254:
            raise jwt.InvalidTokenError()
        if claims.get('type') != 'app':
            raise jwt.InvalidTokenError()
        return Actor(subject, email.lower())
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, 'Sign-in verification is temporarily unavailable. Retry shortly.')
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, 'Your sign-in has expired or is invalid. Sign in again.')


def actor():
    return actor_context.get()


def require_membership(db, classroom_id):
    current = actor()
    if current is None or classroom_id is None:
        raise HTTPException(403, 'Sign in with an enrolled classroom account.')
    row = db.execute('''SELECT 1 FROM classroom_memberships
        WHERE classroom_id=? AND email=? AND enabled=1''', (classroom_id,current.email)).fetchone()
    if row is None:
        raise HTTPException(403, 'Your account is not enrolled in this classroom. Contact your instructor.')


def require_owner(db, session):
    # User-bound sessions stay protected even if an operator later turns auth off.
    if MODE == 'cloudflare' or session['owner_subject']:
        current = actor()
        if current is None or session['owner_subject'] != current.subject or session['owner_email'] != current.email:
            raise HTTPException(403, 'This lab belongs to another account or predates verified login.')
        require_membership(db, session['classroom_id'])


def is_platform_admin():
    current = actor()
    return MODE == 'cloudflare' and current is not None and current.email in ADMIN_EMAILS


def require_admin():
    if not is_admin():
        raise HTTPException(403, 'Administrator access required.')
    return actor()


def admin_colleges(db):
    current = actor()
    if MODE != 'cloudflare' or current is None:
        return []
    return [row[0] for row in db.execute(
        'SELECT college_id FROM college_admins WHERE email=? AND enabled=1', (current.email,))]


def is_admin():
    if is_platform_admin():
        return True
    if MODE != 'cloudflare' or actor() is None:
        return False
    from contextlib import closing
    import classrooms
    with closing(classrooms.connect()) as db:
        return bool(admin_colleges(db))


def require_platform_admin():
    if not is_platform_admin():
        raise HTTPException(403, 'Platform administrator access required.')
    return actor()


def require_college_admin(db, college_id):
    if is_platform_admin():
        return
    if college_id is None or college_id not in admin_colleges(db):
        raise HTTPException(403, 'This college is outside your administrator scope.')
