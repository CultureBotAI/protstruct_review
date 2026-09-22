#!/usr/bin/env python3
"""Safe YAML loading that rejects duplicate mapping keys."""
from __future__ import annotations

from typing import Any

import yaml


class DuplicateYamlKeyError(yaml.YAMLError):
    """A YAML mapping repeats a key and is therefore human-ambiguous."""


class UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that fails instead of applying last-key-wins."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise DuplicateYamlKeyError(
                f"unhashable YAML mapping key at line {key_node.start_mark.line + 1}"
            ) from exc
        if duplicate:
            raise DuplicateYamlKeyError(
                f"duplicate YAML mapping key {key!r} at line "
                f"{key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def strict_yaml_load(text: str) -> Any:
    """Parse trusted-repository YAML without accepting duplicate keys."""
    return yaml.load(text, Loader=UniqueKeySafeLoader)
