"""Resolve declared port widths with bounded integer-only computations."""

import ast
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re

from .corpus_conditions import evaluate_condition


def _integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean port width")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ValueError("port width is not a numeric literal") from None
    if not number.is_finite() or number != number.to_integral_value() or abs(number) > 1_000_000:
        raise ValueError("port width is not a bounded integer")
    return int(number)


def _environment(instance: Mapping, defaults: Mapping) -> dict:
    result = {}
    for values in (defaults, instance):
        seen = set()
        for name, value in values.items():
            folded = name.casefold()
            if folded in seen:
                raise ValueError("ambiguous dimension parameter")
            seen.add(folded)
            result[folded] = value
    return result


def _expression(text: str, values: dict) -> int:
    tree = ast.parse(text, mode="eval")
    if len(list(ast.walk(tree))) > 128:
        raise ValueError("dimension expression is too large")

    def visit(node):
        if isinstance(node, ast.Constant):
            return _integer(node.value)
        if isinstance(node, ast.Name):
            return _integer(values[node.id.casefold()])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            left, right = visit(node.left), visit(node.right)
            return _integer(left + right if isinstance(node.op, ast.Add) else left - right)
        raise ValueError("unsupported dimension expression")

    return visit(tree.body)


def declared_dimension(name: str, instance: Mapping, defaults: Mapping, computations: str | None) -> int:
    values = _environment(instance, defaults)
    key = name.casefold()
    if key in values:
        value = _integer(values[key])
    else:
        if not computations or len(computations) > 32768:
            raise ValueError("dimension has no admitted declaration")
        lines = computations.splitlines()
        if len(lines) > 512:
            raise ValueError("dimension program is too large")
        frames = []
        active = True
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            if line.upper().startswith("#IF "):
                condition = evaluate_condition(line[4:], values, {}, case_insensitive=True) if active else False
                frames.append((active, condition, False))
                if len(frames) > 32:
                    raise ValueError("dimension condition nesting is too deep")
                active = active and condition
            elif line.upper() == "#ELSE":
                if not frames or frames[-1][2]:
                    raise ValueError("invalid dimension else branch")
                parent, condition, _ = frames[-1]
                frames[-1] = (parent, condition, True)
                active = parent and not condition
            elif line.upper() == "#ENDIF":
                if not frames:
                    raise ValueError("unmatched dimension conditional")
                active = frames.pop()[0]
            elif active:
                match = re.fullmatch(r"INTEGER\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)", line, re.IGNORECASE)
                if not match:
                    raise ValueError("unsupported dimension computation")
                values[match[1].casefold()] = _expression(match[2], values)
        if frames or key not in values:
            raise ValueError("dimension computation is incomplete")
        value = _integer(values[key])
    if value <= 0:
        raise ValueError("active port width must be positive")
    return value
