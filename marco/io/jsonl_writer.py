from __future__ import annotations

import io
import json

from ..core.models import Edge, Node


class JsonlWriter:
    def __init__(self, nodes_path: str, edges_path: str, manifest_path: str | None = None):
        self._nodes_fp: io.TextIOBase | None = None
        self._edges_fp: io.TextIOBase | None = None
        self._manifest_path: str | None = manifest_path
        try:
            self._nodes_fp = open(nodes_path, "w", encoding="utf-8")  # noqa: SIM115
            self._edges_fp = open(edges_path, "w", encoding="utf-8")  # noqa: SIM115
        except Exception:
            if self._nodes_fp is not None:
                self._nodes_fp.close()
                self._nodes_fp = None
            raise

    def write_node(self, node: Node) -> None:
        if self._nodes_fp is None:
            raise RuntimeError("JsonlWriter is closed or was not initialized")
        data = {
            "symbol": node.symbol,
            "module": node.module,
            "name": node.name,
            "address": node.address,
            "kind": node.kind,
            "props": node.props,
        }
        self._nodes_fp.write(json.dumps(data) + "\n")

    def write_edge(self, edge: Edge) -> None:
        if self._edges_fp is None:
            raise RuntimeError("JsonlWriter is closed or was not initialized")
        data = {"src": edge.src, "dst": edge.dst, "kind": edge.kind, "props": edge.props}
        self._edges_fp.write(json.dumps(data) + "\n")

    def close(self):
        if self._nodes_fp:
            self._nodes_fp.close()
            self._nodes_fp = None
        if self._edges_fp:
            self._edges_fp.close()
            self._edges_fp = None
        # manifest is written by caller
