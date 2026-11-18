"""Marker bases the API maps to a status: ClientInputError -> 400, NotConfigured -> 503.

Anything else that escapes a route is a server fault: logged, answered with a generic 500.
They keep the builtin base so existing `except ValueError` / `except RuntimeError` still catch them.
"""
from __future__ import annotations


class ClientInputError(ValueError):
    """The request (or something it names) is wrong: the API answers 400 with the message."""


class NotConfigured(RuntimeError):
    """A needed key, file or service is not set up: the API answers 503 with the message."""
