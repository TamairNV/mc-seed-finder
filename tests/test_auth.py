import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import AccessVerifier, Denied, PanelVerifier
from app.tnv_access import AccessGuard

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


def panel(status_by_email):
    guard = AccessGuard("seed-finder", TEAM, AUD, key_lookup=lambda _: KEY.public_key(),
                        fetch=lambda url: status_by_email[url.rsplit("/", 1)[1].replace("%40", "@")])
    return PanelVerifier(AccessVerifier(TEAM, AUD, jwks_client=FakeKeys()), guard)


def test_listed_person_passes_with_their_role():
    v = panel({"a@b.c": (200, {"role": "admin", "roles": ["user", "admin"]})})
    assert v.verify(token())["role"] == "admin"


def test_person_not_on_the_site_denied():
    with pytest.raises(Denied) as e:
        panel({"a@b.c": (404, {})}).verify(token())
    assert e.value.status == 403


def test_bad_token_denied_before_asking_the_panel():
    def never(url):
        raise AssertionError("asked the panel")
    guard = AccessGuard("seed-finder", TEAM, AUD, key_lookup=lambda _: KEY.public_key(), fetch=never)
    with pytest.raises(Denied) as e:
        PanelVerifier(AccessVerifier(TEAM, AUD, jwks_client=FakeKeys()), guard).verify(token(aud="other"))
    assert e.value.status == 403


def test_panel_away_allows_only_the_lowest_role():
    def down(url):
        raise OSError("no route")
    guard = AccessGuard("seed-finder", TEAM, AUD, key_lookup=lambda _: KEY.public_key(), fetch=down)
    v = PanelVerifier(AccessVerifier(TEAM, AUD, jwks_client=FakeKeys()), guard)
    assert v.verify(token())["role"] == "user"


def test_unconfigured_panel_fails_closed():
    with pytest.raises(Denied) as e:
        PanelVerifier(AccessVerifier(TEAM, AUD, jwks_client=FakeKeys()), None).verify(token())
    assert e.value.status == 503
