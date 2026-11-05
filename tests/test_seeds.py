import pytest

from app import seeds


@pytest.mark.parametrize("text,seed", [
    ("hello", 99162322),
    ("polygenelubricants", -2147483648),
    ("  123  ", 123),
    ("-5", -5),
    ("9223372036854775807", 9223372036854775807),
    ("-9223372036854775808", -9223372036854775808),
])
def test_parse(text, seed):
    assert seeds.parse(text) == seed


@pytest.mark.parametrize("text", ["", "   ", "9223372036854775808", "-9223372036854775809"])
def test_parse_rejects(text):
    with pytest.raises(seeds.InvalidSeed):
        seeds.parse(text)
