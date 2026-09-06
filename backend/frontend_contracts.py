"""Small source/catalog assertions shared by backend frontend-contract tests.

These are static architecture checks, not browser behavior claims. Match quote
and whitespace variations while checking actual translation namespaces/keys.
"""
import json
from pathlib import Path
import re

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def catalog_message(namespace: str, key: str, *, placeholder: str | None = None) -> str:
    english = ""
    for locale in ("en", "uz", "ru", "ar"):
        value = json.loads((FRONTEND / "messages" / locale / f"{namespace}.json").read_text())
        for segment in key.split("."):
            value = value[segment]
        assert isinstance(value, str) and value.strip(), (locale, namespace, key)
        if placeholder:
            assert "{" + placeholder + "}" in value, (locale, namespace, key)
        if locale == "en":
            english = value
    return english


def translated(source: str, namespace: str, key: str, *, translator: str = "t", placeholder: str | None = None) -> str:
    assert re.search(r"useTranslations\(\s*['\"]" + re.escape(namespace) + r"['\"]\s*\)", source)
    assert re.search(r"\b" + re.escape(translator) + r"\(\s*['\"]" + re.escape(key) + r"['\"]\s*[,)]", source)
    return catalog_message(namespace, key, placeholder=placeholder)


def literal_call(source: str, function: str, argument: str) -> None:
    assert re.search(re.escape(function) + r"\(\s*['\"]" + re.escape(argument) + r"['\"]\s*[,)]", source)
