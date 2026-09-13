"""Secret references and their resolution.

A secret is never an ordinary settings value (M00-SPEC-002 R15). Configuration
holds a *reference* — an opaque `scheme:identifier` pointing at a secret held
somewhere else — and a resolver turns that reference into a value at the point
of use.

The reference is a distinct type, so assigning a plain-text secret to a
secret-bearing field fails at load rather than passing review (R16). Resolved
values are wrapped so no representation renders them (R17).

At M00 the only scheme is ``env:``. Adding an enterprise secret manager later
is a new resolver, not a change to the settings model (R19).
"""

from __future__ import annotations

import os
import re
from typing import Annotated, Protocol, runtime_checkable

from pydantic import GetPydanticSchema, SecretStr
from pydantic_core import core_schema

__all__ = [
    "EnvSecretResolver",
    "SecretRef",
    "SecretResolutionError",
    "SecretResolver",
]

# scheme:identifier — scheme is lowercase alphanumeric, identifier is non-empty
# and carries no whitespace.
_REFERENCE_PATTERN = re.compile(r"^(?P<scheme>[a-z][a-z0-9_-]*):(?P<identifier>\S+)$")

_SUPPORTED_SCHEMES = frozenset({"env"})


class SecretResolutionError(RuntimeError):
    """A secret reference could not be resolved.

    The message names the reference; it never carries the value that was, or
    was not, found.
    """


class _SecretRef:
    """An opaque pointer to a secret, never the secret itself."""

    __slots__ = ("_identifier", "_scheme")

    def __init__(self, scheme: str, identifier: str) -> None:
        self._scheme = scheme
        self._identifier = identifier

    @property
    def scheme(self) -> str:
        return self._scheme

    @property
    def identifier(self) -> str:
        return self._identifier

    def __str__(self) -> str:
        # The reference is not itself sensitive, but keeping one rendering
        # everywhere means callers never have to think about which is safe.
        return f"{self._scheme}:{self._identifier}"

    def __repr__(self) -> str:
        return f"SecretRef({self._scheme}:{self._identifier})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _SecretRef):
            return NotImplemented
        return (self._scheme, self._identifier) == (other._scheme, other._identifier)

    def __hash__(self) -> int:
        return hash((self._scheme, self._identifier))


def _validate(value: object) -> _SecretRef:
    if isinstance(value, _SecretRef):
        return value
    if not isinstance(value, str):
        msg = "must be a secret reference of the form 'scheme:identifier'"
        raise ValueError(msg)
    match = _REFERENCE_PATTERN.match(value)
    if match is None:
        # Deliberately does not echo the offending value: it may well be the
        # plain-text secret someone tried to inline (R4, R16).
        msg = (
            "must be a secret reference of the form 'scheme:identifier', "
            "not an inline value"
        )
        raise ValueError(msg)
    scheme = match.group("scheme")
    if scheme not in _SUPPORTED_SCHEMES:
        supported = ", ".join(sorted(_SUPPORTED_SCHEMES))
        msg = f"uses unsupported secret scheme '{scheme}'; supported: {supported}"
        raise ValueError(msg)
    return _SecretRef(scheme, match.group("identifier"))


SecretRef = Annotated[
    _SecretRef,
    GetPydanticSchema(
        lambda _source, _handler: core_schema.no_info_plain_validator_function(
            _validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )
    ),
]
"""A reference to a secret. Assigning a plain value to this type fails at load."""


@runtime_checkable
class SecretResolver(Protocol):
    """Turns a reference into a value at the point of use."""

    def resolve(self, ref: _SecretRef) -> SecretStr: ...


class EnvSecretResolver:
    """Resolves ``env:NAME`` references from the process environment.

    This is the M00 resolver. A managed-secret-store resolver added later
    implements the same protocol and requires no settings-model change.
    """

    def resolve(self, ref: _SecretRef) -> SecretStr:
        if ref.scheme != "env":
            msg = f"cannot resolve secret reference '{ref}': unsupported scheme"
            raise SecretResolutionError(msg)
        value = os.environ.get(ref.identifier)
        if value is None:
            msg = f"secret reference '{ref}' is not set in the environment"
            raise SecretResolutionError(msg)
        return SecretStr(value)
