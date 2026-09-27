"""Fake-mail aliases: name+word1234@domain — stdlib only."""
import re
import secrets

WORDS = ("amber", "bison", "cedar", "delta", "ember", "fjord", "globe", "harbor",
         "indigo", "jade", "karma", "lunar", "mango", "nova", "onyx", "pearl",
         "quartz", "raven", "sable", "tulip", "umbra", "violet", "willow",
         "xenon", "yonder", "zephyr", "clover", "dune", "echo", "flint")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_email(s: str) -> bool:
    return bool(_EMAIL.match((s or "").strip()))


def make_alias(email: str) -> str:
    """Babaie640@gmail.com -> Babaie640+<word><4 digits>@gmail.com"""
    email = (email or "").strip()
    local, _, domain = email.rpartition("@")
    if not local or not domain:
        raise ValueError("bad email")
    word = secrets.choice(WORDS)
    digits = secrets.randbelow(10000)
    return f"{local}+{word}{digits:04d}@{domain}"
