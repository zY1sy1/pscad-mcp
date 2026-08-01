"""Small, defensive primitives shared by PSCAD 4.6 automation operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from .base import BackendError


_MAX_ATTRIBUTES = 16
_MAX_CHILDREN = 16
_MAX_TEXT = 256
_MAX_DEPTH = 4
_KIND_BY_SUFFIX = {".pscx": "case", ".pslx": "library"}
_KIND_BY_TARGET = {"emtdc": "case", "case": "case", "library": "library"}
_NAME_ATTRIBUTE = re.compile(
    r"(?P<prefix>(?<![:\w.-])name\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_XML_ENCODING = re.compile(
    br"<\?xml[^>]*\bencoding\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_RESERVED_RESPONSE_KEYS = {"tag", "children", "attributes", "reserved_attributes"}


def _bounded_text(value: str, limit: int = _MAX_TEXT) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Return diagnostics that can be serialized without invoking vendor proxies."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _bounded_text(value)
    if depth >= _MAX_DEPTH:
        return {"type": type(value).__name__}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_ATTRIBUTES:
                break
            result[_bounded_text(str(key), 64)] = _json_safe(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [
            _json_safe(item, depth=depth + 1)
            for item in value[:_MAX_CHILDREN]
        ]
    return {"type": type(value).__name__}


def response_payload(response: Any) -> dict[str, Any]:
    """Extract a bounded, JSON-safe diagnostic summary from an XML response."""
    if not isinstance(response, ET.Element):
        payload: dict[str, Any] = {"type": type(response).__name__}
        if isinstance(response, str):
            payload["value"] = _bounded_text(response)
        return payload

    attributes = {
        _bounded_text(key, 64): _bounded_text(value)
        for index, (key, value) in enumerate(response.attrib.items())
        if index < _MAX_ATTRIBUTES and isinstance(key, str) and isinstance(value, str)
    }
    payload = {"tag": _bounded_text(response.tag) if isinstance(response.tag, str) else ""}
    reserved_attributes = {
        key: value for key, value in attributes.items() if key in _RESERVED_RESPONSE_KEYS
    }
    payload.update(
        {key: value for key, value in attributes.items() if key not in _RESERVED_RESPONSE_KEYS}
    )
    if reserved_attributes:
        payload["reserved_attributes"] = reserved_attributes
    children = []
    for child in list(response)[:_MAX_CHILDREN]:
        child_payload: dict[str, str] = {
            "tag": _bounded_text(child.tag) if isinstance(child.tag, str) else ""
        }
        if isinstance(child.text, str) and child.text:
            child_payload["text"] = _bounded_text(child.text)
        children.append(child_payload)
    if children:
        payload["children"] = children
    return payload


def require_success(response: Any, operation: str, details: Mapping[str, Any]) -> Any:
    """Accept only explicit successful PSCAD XML command responses."""
    success = response.get("success") if isinstance(response, ET.Element) else None
    if not isinstance(success, str) or success.casefold() != "true":
        safe_details = _json_safe(details)
        if not isinstance(safe_details, dict):
            safe_details = {"details": safe_details}
        safe_details["response"] = response_payload(response)
        raise BackendError(
            "PSCAD_COMMAND_FAILED",
            f"PSCAD 4.6.2 command '{operation}' failed.",
            "legacy",
            operation,
            safe_details,
        )
    return response


def project_kind(root: ET.Element, suffix: str) -> str:
    """Derive a PSCAD project kind and reject XML/extension disagreements."""
    if not isinstance(root, ET.Element):
        raise ValueError("Project XML root is invalid.")
    suffix_kind = _KIND_BY_SUFFIX.get(str(suffix).casefold())
    if suffix_kind is None:
        raise ValueError(f"Unsupported PSCAD project suffix: {suffix}")

    target = root.get("Target") or root.get("target")
    if target is None:
        return suffix_kind
    target_kind = _KIND_BY_TARGET.get(target.casefold())
    if target_kind is None:
        raise ValueError(f"Unsupported PSCAD project Target marker: {target}")
    if target_kind != suffix_kind:
        raise ValueError(
            f"PSCAD project Target marker '{target}' conflicts with suffix '{suffix}'."
        )
    return target_kind


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def intersects(self, other: "Rect", *, margin: int = 0) -> bool:
        return not (
            self.x + self.width + margin <= other.x
            or other.x + other.width + margin <= self.x
            or self.y + self.height + margin <= other.y
            or other.y + other.height + margin <= self.y
        )


def snap_to_grid(value: int, grid: int = 18) -> int:
    if grid <= 0:
        raise ValueError("grid must be positive")
    return (value // grid) * grid


def candidate_rectangles(
    near: tuple[int, int],
    width: int,
    height: int,
    *,
    grid: int = 18,
    rings: int = 8,
) -> Iterator[Rect]:
    """Yield unique grid-aligned placements in deterministic expanding rings."""
    if rings < 0:
        raise ValueError("rings must not be negative")
    origin_x = snap_to_grid(near[0], grid)
    origin_y = snap_to_grid(near[1], grid)
    yield Rect(origin_x, origin_y, width, height)
    for ring in range(1, rings + 1):
        for dx in range(-ring, ring + 1):
            yield Rect(origin_x + dx * grid, origin_y - ring * grid, width, height)
        for dy in range(-ring + 1, ring + 1):
            yield Rect(origin_x + ring * grid, origin_y + dy * grid, width, height)
        for dx in range(ring - 1, -ring - 1, -1):
            yield Rect(origin_x + dx * grid, origin_y + ring * grid, width, height)
        for dy in range(ring - 1, -ring, -1):
            yield Rect(origin_x - ring * grid, origin_y + dy * grid, width, height)


@dataclass(frozen=True)
class _XmlTag:
    start: int
    end: int
    text: str
    name: str
    closing: bool
    self_closing: bool


def _xml_tags(text: str) -> Iterator[_XmlTag]:
    """Tokenize XML tags without normalizing the original document text."""
    position = 0
    while True:
        start = text.find("<", position)
        if start < 0:
            return
        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
            position = len(text) if end < 0 else end + 3
            continue
        if text.startswith("<![CDATA[", start):
            end = text.find("]]>", start + 9)
            position = len(text) if end < 0 else end + 3
            continue
        end = start + 1
        quote: str | None = None
        while end < len(text):
            char = text[end]
            if quote:
                if char == quote:
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == ">":
                break
            end += 1
        if end >= len(text):
            return
        raw = text[start : end + 1]
        position = end + 1
        content = raw[1:-1].strip()
        if not content or content.startswith(("?", "!")):
            continue
        closing = content.startswith("/")
        name_text = content[1:].lstrip() if closing else content
        name = name_text.split(None, 1)[0].rstrip("/")
        yield _XmlTag(start, end + 1, raw, name, closing, content.endswith("/"))


def _replace_name_attribute(tag_text: str, new_name: str) -> str:
    match = _NAME_ATTRIBUTE.search(tag_text)
    if match is None:
        raise ValueError("Project identity tag has no name attribute.")
    quote = match.group("quote")
    escaped = escape(new_name, {quote: "&quot;" if quote == '"' else "&apos;"})
    return tag_text[: match.start()] + match.group("prefix") + quote + escaped + quote + tag_text[match.end() :]


@dataclass(frozen=True)
class _DocumentEncoding:
    codec: str
    bom: bytes = b""


def _document_encoding(data: bytes) -> _DocumentEncoding:
    for bom, codec in (
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if data.startswith(bom):
            return _DocumentEncoding(codec, bom)
    for signature, codec in (
        (b"\x00\x00\x00<", "utf-32-be"),
        (b"<\x00\x00\x00", "utf-32-le"),
        (b"\x00<\x00?", "utf-16-be"),
        (b"<\x00?\x00", "utf-16-le"),
    ):
        if data.startswith(signature):
            return _DocumentEncoding(codec)
    match = _XML_ENCODING.search(data[:512])
    return _DocumentEncoding(match.group(1).decode("ascii") if match else "utf-8")


def rewrite_project_identity(
    source: str | Path,
    destination: str | Path,
    new_name: str,
    *,
    expected_root: str = "project",
) -> None:
    """Atomically copy a project while editing only its identity attributes."""
    source_path = Path(source)
    destination_path = Path(destination)
    original = source_path.read_bytes()
    encoding = _document_encoding(original)
    text = original[len(encoding.bom) :].decode(encoding.codec)
    root = ET.fromstring(text)
    if root.tag != expected_root:
        raise ValueError(
            f"Expected root <{expected_root}> but found <{root.tag}>."
        )
    source_kind = project_kind(root, source_path.suffix)
    if project_kind(root, destination_path.suffix) != source_kind:
        raise ValueError("Source and destination PSCAD project kinds differ.")

    root_tag: _XmlTag | None = None
    replacements: list[tuple[int, int, str]] = []
    depth = 0
    old_name = root.get("name")
    if old_name is None:
        raise ValueError("Project root has no name attribute.")
    original_outputs = [child for child in root if child.tag == "output"]
    matching_output_indices = {
        index
        for index, output in enumerate(original_outputs)
        if output.get("name") == old_name
    }
    direct_output_index = 0
    for tag in _xml_tags(text):
        if tag.closing:
            depth -= 1
            continue
        if root_tag is None:
            if tag.name != expected_root:
                continue
            root_tag = tag
            depth = 1
            replacements.append((tag.start, tag.end, _replace_name_attribute(tag.text, new_name)))
            if tag.self_closing:
                depth = 0
            continue
        if depth == 1 and tag.name == "output":
            if direct_output_index in matching_output_indices:
                replacements.append((tag.start, tag.end, _replace_name_attribute(tag.text, new_name)))
            direct_output_index += 1
        if not tag.self_closing:
            depth += 1
    if root_tag is None:
        raise ValueError(f"Expected root <{expected_root}> was not found in XML text.")

    rewritten = text
    for start, end, replacement in reversed(replacements):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    rewritten_bytes = encoding.bom + rewritten.encode(encoding.codec)
    rewritten_root = ET.fromstring(rewritten)
    if rewritten_root.tag != expected_root or rewritten_root.get("name") != new_name:
        raise ValueError("Rewritten project XML failed identity validation.")
    rewritten_outputs = [child for child in rewritten_root if child.tag == "output"]
    if any(
        index >= len(rewritten_outputs)
        or rewritten_outputs[index].get("name") != new_name
        for index in matching_output_indices
    ):
        raise ValueError("Rewritten project output identity validation failed.")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            dir=destination_path.parent,
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(rewritten_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, destination_path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
