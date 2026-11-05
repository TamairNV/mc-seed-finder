import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import AccessVerifier, Denied

TEAM = "team.example.com"
AUD = "aud-123"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKeys:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def token(key=KEY, alg="RS256", **overrides):
    claims = {"aud": AUD, "iss": f"https://{TEAM}", "exp": time.time() + 60, "email": "a@b.c", **overrides}
    return jwt.encode(claims, key, algorithm=alg)


@pytest.fixture
def verifier():
    return AccessVerifier(TEAM, AUD, jwks_client=FakeKeys())


def test_valid_token_passes(verifier):
    assert verifier.verify(token())["email"] == "a@b.c"


@pytest.mark.parametrize("bad", [
    None, "", "garbage",
    token(exp=time.time() - 60), token(aud="other"), token(iss="https://evil.example.com"),
    token(key=OTHER_KEY), jwt.encode({"aud": AUD, "iss": f"https://{TEAM}"}, "x" * 40, algorithm="HS256"),
])
def test_bad_tokens_denied(verifier, bad):
    with pytest.raises(Denied) as e:
        verifier.verify(bad)
    assert e.value.status == 403


@pytest.mark.parametrize("team,aud", [(None, AUD), (TEAM, None), ("", ""), (None, None)])
def test_unset_config_denies(team, aud):
    with pytest.raises(Denied) as e:
        AccessVerifier(team, aud, jwks_client=FakeKeys()).verify(token())
    assert e.value.status == 503


def test_key_fetch_failure_denies():
    class Down:
        def get_signing_key_from_jwt(self, token):
            raise jwt.exceptions.PyJWKClientConnectionError("down")

    with pytest.raises(Denied) as e:
        AccessVerifier(TEAM, AUD, jwks_client=Down()).verify(token())
    assert e.value.status == 503


def test_unknown_key_id_is_403():
    class NoKey:
        def get_signing_key_from_jwt(self, token):
            raise jwt.exceptions.PyJWKClientError("no key")

    with pytest.raises(Denied) as e:
        AccessVerifier(TEAM, AUD, jwks_client=NoKey()).verify(token())
    assert e.value.status == 403
