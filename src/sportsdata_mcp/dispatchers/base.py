"""Dispatcher protocol. A dispatcher is one tool that serves many operations,
backed by a catalogue MCP resource the model reads to discover valid operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class DispatcherFactory(Protocol):
    def __call__(self, disp, spec, http) -> Callable: ...
