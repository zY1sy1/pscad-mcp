"""Safe evaluation for the closed PSCAD conditional-port expression grammar."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TypeAlias

_TOKEN = re.compile(
    r"\s*(?:(?P<op>&&|\|\||==|!=|>|[!+()])|"
    r"(?P<identifier>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?P<number>[0-9]+(?:\.[0-9]+)?))"
)
_COMPARISONS = frozenset({"==", "!=", ">"})
_MAX_TOKENS = 256
_MAX_NESTING = 64


class ConditionUnresolved(ValueError):
    """Raised when a condition cannot be evaluated under the closed grammar."""


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


@dataclass(frozen=True)
class _Literal:
    value: bool | Decimal


@dataclass(frozen=True)
class _Identifier:
    name: str


@dataclass(frozen=True)
class _Unary:
    operator: str
    operand: _Node


@dataclass(frozen=True)
class _Binary:
    operator: str
    left: _Node
    right: _Node


_Node: TypeAlias = _Literal | _Identifier | _Unary | _Binary
_Scalar: TypeAlias = bool | Decimal


def _tokens(expression: str) -> tuple[_Token, ...]:
    result = []
    position = 0
    nesting = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None or match.end() == position:
            raise ConditionUnresolved("unsupported conditional-port syntax")
        if match.group("op") is not None:
            value = match.group("op")
            result.append(_Token("op", value))
            if value == "(":
                nesting += 1
                if nesting > _MAX_NESTING:
                    raise ConditionUnresolved(
                        "conditional-port grouping is too deep"
                    )
            elif value == ")":
                nesting -= 1
                if nesting < 0:
                    raise ConditionUnresolved(
                        "conditional-port grouping is invalid"
                    )
        elif match.group("identifier") is not None:
            result.append(_Token("identifier", match.group("identifier")))
        else:
            result.append(_Token("number", match.group("number")))
        if len(result) > _MAX_TOKENS:
            raise ConditionUnresolved("conditional-port expression is too complex")
        position = match.end()
    return tuple(result)


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self._tokens = tokens
        self._index = 0

    def _current(self) -> _Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _accept(self, value: str) -> bool:
        current = self._current()
        if current is None or current.value != value:
            return False
        self._index += 1
        return True

    def _take(self) -> _Token:
        current = self._current()
        if current is None:
            raise ConditionUnresolved("conditional-port expression is incomplete")
        self._index += 1
        return current

    def _expect(self, value: str) -> None:
        if not self._accept(value):
            raise ConditionUnresolved("conditional-port grouping is invalid")

    def require_end(self) -> None:
        if self._current() is not None:
            raise ConditionUnresolved("conditional-port expression has extra tokens")

    def parse_or(self) -> _Node:
        result = self.parse_and()
        while self._accept("||"):
            result = _Binary("||", result, self.parse_and())
        return result

    def parse_and(self) -> _Node:
        result = self.parse_comparison()
        while self._accept("&&"):
            result = _Binary("&&", result, self.parse_comparison())
        return result

    def parse_comparison(self) -> _Node:
        result = self.parse_addition()
        current = self._current()
        if current is not None and current.value in _COMPARISONS:
            operator = self._take().value
            result = _Binary(operator, result, self.parse_addition())
            trailing = self._current()
            if trailing is not None and trailing.value in _COMPARISONS:
                raise ConditionUnresolved("chained comparisons are unsupported")
        return result

    def parse_addition(self) -> _Node:
        result = self.parse_unary()
        while self._accept("+"):
            result = _Binary("+", result, self.parse_unary())
        return result

    def parse_unary(self) -> _Node:
        if self._accept("!"):
            return _Unary("!", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> _Node:
        if self._accept("("):
            result = self.parse_or()
            self._expect(")")
            return result
        token = self._take()
        if token.kind == "number":
            return _Literal(Decimal(token.value))
        if token.kind != "identifier":
            raise ConditionUnresolved("conditional-port operand is invalid")
        if token.value == "true":
            return _Literal(True)
        if token.value == "false":
            return _Literal(False)
        return _Identifier(token.value)


def _coerce_value(value: object) -> _Scalar:
    if isinstance(value, bool):
        return value
    if isinstance(value, (tuple, list, dict, set)) or value is None:
        raise ConditionUnresolved("conditional-port parameter is ambiguous")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.casefold() == "true":
            return True
        if stripped.casefold() == "false":
            return False
        candidate = stripped
    elif isinstance(value, (Decimal, int, float)):
        candidate = str(value)
    else:
        raise ConditionUnresolved("conditional-port parameter type is unsupported")
    try:
        numeric = Decimal(candidate)
    except (InvalidOperation, ValueError):
        raise ConditionUnresolved(
            "conditional-port parameter is not numeric"
        ) from None
    if not numeric.is_finite():
        raise ConditionUnresolved("conditional-port parameter is not finite")
    return numeric


def _resolve_identifier(
    name: str,
    instance_values: Mapping[str, object],
    definition_defaults: Mapping[str, object],
) -> _Scalar:
    if name in instance_values:
        return _coerce_value(instance_values[name])
    if name in definition_defaults:
        return _coerce_value(definition_defaults[name])
    raise ConditionUnresolved("conditional-port parameter is missing")


def _as_boolean(value: _Scalar) -> bool:
    return value if isinstance(value, bool) else value != 0


def _as_number(value: _Scalar) -> Decimal:
    if isinstance(value, bool):
        raise ConditionUnresolved("boolean arithmetic is unsupported")
    return value


def _equality_values(left: _Scalar, right: _Scalar) -> tuple[_Scalar, _Scalar]:
    if isinstance(left, bool) and isinstance(right, Decimal):
        left = Decimal(int(left))
    elif isinstance(left, Decimal) and isinstance(right, bool):
        right = Decimal(int(right))
    return left, right


def _evaluate(
    node: _Node,
    instance_values: Mapping[str, object],
    definition_defaults: Mapping[str, object],
) -> _Scalar:
    if isinstance(node, _Literal):
        return node.value
    if isinstance(node, _Identifier):
        return _resolve_identifier(node.name, instance_values, definition_defaults)
    if isinstance(node, _Unary):
        return not _as_boolean(
            _evaluate(node.operand, instance_values, definition_defaults)
        )

    left = _evaluate(node.left, instance_values, definition_defaults)
    if node.operator == "&&":
        return _as_boolean(left) and _as_boolean(
            _evaluate(node.right, instance_values, definition_defaults)
        )
    if node.operator == "||":
        return _as_boolean(left) or _as_boolean(
            _evaluate(node.right, instance_values, definition_defaults)
        )

    right = _evaluate(node.right, instance_values, definition_defaults)
    if node.operator == "+":
        return _as_number(left) + _as_number(right)
    if node.operator in {"==", "!="}:
        left, right = _equality_values(left, right)
        equal = left == right
        return equal if node.operator == "==" else not equal
    if node.operator == ">":
        return _as_number(left) > _as_number(right)
    raise ConditionUnresolved("conditional-port operator is unsupported")


def evaluate_condition(
    expression: str | None,
    instance_values: Mapping[str, object],
    definition_defaults: Mapping[str, object],
) -> bool:
    """Evaluate one conditional-port expression under the closed grammar."""

    if expression is None or not expression.strip():
        return True
    parser = _Parser(_tokens(expression.strip()))
    tree = parser.parse_or()
    parser.require_end()
    return _as_boolean(_evaluate(tree, instance_values, definition_defaults))
