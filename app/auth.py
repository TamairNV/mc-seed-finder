"""Verifies the token Cloudflare Access adds, so the origin isn't trusted blindly. Fails closed."""

import jwt

from app.tnv_access import AccessDenied, AccessGuard


class Denied(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class AccessVerifier:
    def __init__(self, team_domain: str | None, aud: str | None, jwks_client=None):
        self._team = team_domain
        self._aud = aud
        self._keys = jwks_client
        if self._keys is None and team_domain:
            self._keys = jwt.PyJWKClient(f"https://{team_domain}/cdn-cgi/access/certs", cache_keys=True)

    def verify(self, token: str | None) -> dict:
        if not self._team or not self._aud:
            raise Denied(503, "Cloudflare Access is not configured")
        if not token:
            raise Denied(403, "Missing Cloudflare Access token")
        try:
            key = self._keys.get_signing_key_from_jwt(token).key
        except jwt.exceptions.PyJWKClientConnectionError as e:
            raise Denied(503, "Could not reach Cloudflare to check the login") from e
        except jwt.exceptions.PyJWTError as e:
            raise Denied(403, "Invalid Cloudflare Access token") from e
        try:
            return jwt.decode(token, key, algorithms=["RS256"], audience=self._aud,
                              issuer=f"https://{self._team}", options={"require": ["exp", "aud", "iss"]})
        except jwt.exceptions.PyJWTError as e:
            raise Denied(403, "Invalid Cloudflare Access token") from e


class PanelVerifier:
    """Checks the token, then asks the access panel whether this person is on the site."""

    def __init__(self, tokens: AccessVerifier, guard: AccessGuard | None):
        self._tokens = tokens
        self._guard = guard

    def verify(self, token: str | None) -> dict:
        claims = self._tokens.verify(token)
        if self._guard is None:
            raise Denied(503, "The access panel is not configured")
        try:
            return {**claims, "role": self._guard.check(token).role}
        except AccessDenied as e:
            raise Denied(e.status, str(e)) from e
