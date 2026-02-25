from __future__ import annotations

from dataclasses import dataclass, field


# A node represents a function, which can be both the source and destination of execution.
@dataclass(frozen=True)
class Node:
    symbol: str
    module: str
    name: str
    address: int
    kind: str = "function"  # future: basicblock, object, interface, etc.
    props: dict[str, object] = field(default_factory=dict)


# An edge represents a transition of execution from one function to another.
@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str  # e.g., CALLS, SYSCALL, RPC, COM, IMPORTS
    props: dict[str, object] = field(default_factory=dict)


# The result of a pass over a binary.
@dataclass
class ExtractionResult:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    discovered_modules: set[str] = field(default_factory=set)
