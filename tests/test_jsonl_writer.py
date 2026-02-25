"""Tests for JsonlWriter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marco.core.models import Edge, Node
from marco.io.jsonl_writer import JsonlWriter


class TestJsonlWriter:
    def test_write_node_and_edge(self, tmp_path):
        nodes_path = str(tmp_path / "nodes.jsonl")
        edges_path = str(tmp_path / "edges.jsonl")
        writer = JsonlWriter(nodes_path, edges_path)

        node = Node(symbol="mod!Func", module="mod", name="Func", address=0x1000)
        edge = Edge(src="mod!A", dst="mod!B", kind="CALLS")

        writer.write_node(node)
        writer.write_edge(edge)
        writer.close()

        with open(nodes_path) as f:
            node_data = json.loads(f.readline())
        assert node_data["symbol"] == "mod!Func"
        assert node_data["address"] == 0x1000

        with open(edges_path) as f:
            edge_data = json.loads(f.readline())
        assert edge_data["src"] == "mod!A"
        assert edge_data["dst"] == "mod!B"
        assert edge_data["kind"] == "CALLS"

    def test_close_then_write_raises(self, tmp_path):
        writer = JsonlWriter(str(tmp_path / "n.jsonl"), str(tmp_path / "e.jsonl"))
        writer.close()

        node = Node(symbol="x!Y", module="x", name="Y", address=0)
        with pytest.raises(RuntimeError):
            writer.write_node(node)

        edge = Edge(src="a", dst="b", kind="CALLS")
        with pytest.raises(RuntimeError):
            writer.write_edge(edge)

    def test_partial_open_failure_cleanup(self, tmp_path):
        nodes_path = str(tmp_path / "nodes.jsonl")
        # Use a path that can't be opened (directory as file)
        bad_dir = tmp_path / "bad_edges_dir"
        bad_dir.mkdir()
        edges_path = str(bad_dir)  # Can't open a directory as a file for writing

        with pytest.raises((IsADirectoryError, PermissionError, OSError)):
            JsonlWriter(nodes_path, edges_path)

        # The nodes file should have been cleaned up (closed) on failure
        # Verify we can open the nodes path without issues (no leaked handles)
        if Path(nodes_path).exists():
            with open(nodes_path) as f:
                f.read()
