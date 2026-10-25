"""Convert a Pydantic JSON Schema into the subset accepted by strict structured outputs.

Strict mode requires every object to list all properties in `required` and to set
`additionalProperties: false`. We also strip validation keywords that strict decoding may not
support (lengths, bounds, patterns). Those constraints are NOT lost: they are still enforced by
Pydantic in our own code after parsing. That is the point - decoding guarantees shape, our
validator guarantees the contract.
"""
from __future__ import annotations

import copy

_STRIP = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
          "exclusiveMinimum", "exclusiveMaximum", "pattern", "format", "default",
          "title", "examples", "uniqueItems", "minProperties", "maxProperties"}
_MAPPINGS = {"properties", "$defs", "definitions"}


def _walk(node):
    if isinstance(node, list):
        return [_walk(x) for x in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return {"$ref": node["$ref"]}
    out = {}
    for k, v in node.items():
        if k in _STRIP:
            continue
        if k in _MAPPINGS and isinstance(v, dict):
            out[k] = {name: _walk(sub) for name, sub in v.items()}
        else:
            out[k] = _walk(v)
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties", {})
        out["type"] = "object"
        out["properties"] = props
        out["required"] = list(props.keys())
        out["additionalProperties"] = False
    return out


def to_strict(schema: dict) -> dict:
    return _walk(copy.deepcopy(schema))
