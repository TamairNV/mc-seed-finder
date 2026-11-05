"""Turns what a person typed into a Minecraft seed, the way the game does."""

import re

_MIN = -(2**63)
_MAX = 2**63 - 1


class InvalidSeed(ValueError):
    pass


def _java_hash(text: str) -> int:
    h = 0
    data = text.encode("utf-16-be", "surrogatepass")
    for i in range(0, len(data), 2):
        h = (31 * h + int.from_bytes(data[i:i + 2], "big")) & 0xFFFFFFFF
    return h - 2**32 if h >= 2**31 else h


def parse_number(text: str) -> int:
    if not re.fullmatch(r"-?\d+", text):
        raise InvalidSeed("Seeds in links must be numbers")
    value = int(text)
    if not _MIN <= value <= _MAX:
        raise InvalidSeed("Number seeds must fit a signed 64-bit integer")
    return value


def parse(text: str) -> int:
    text = text.strip()
    if not text:
        raise InvalidSeed("Enter a seed")
    if re.fullmatch(r"-?\d+", text):
        return parse_number(text)
    return _java_hash(text)
