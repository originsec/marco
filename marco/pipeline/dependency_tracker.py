"""Dependency tracking and Mermaid diagram generation."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class DependencyTracker:
    def __init__(self):
        self.dependency_edges: set[tuple[str, str]] = set()
        self.analyzed_modules: set[str] = set()

    def add_module(self, module: str) -> None:
        self.analyzed_modules.add(module.lower())

    def add_dependencies(self, source: str, targets: set[str]) -> None:
        source_lower = source.lower()
        for target in targets:
            self.dependency_edges.add((source_lower, target.lower()))

    def generate_mermaid_diagram(self, output_path: str | Path) -> None:
        try:
            edges_filtered = {
                (s, d)
                for (s, d) in self.dependency_edges
                if s in self.analyzed_modules and d in self.analyzed_modules and s != d
            }

            adjacency: dict[str, set[str]] = {}
            edges_acyclic: set[tuple[str, str]] = set()

            for s, d in sorted(edges_filtered):
                if not self._would_create_cycle(adjacency, s, d):
                    edges_acyclic.add((s, d))
                    adjacency.setdefault(s, set()).add(d)

            md_lines: list[str] = []
            md_lines.append("# Dependency Tree")
            md_lines.append("")
            md_lines.append("```mermaid")
            md_lines.append("graph TD")

            for mod in sorted(self.analyzed_modules):
                md_lines.append(f"    {self._mermaid_id(mod)}[{mod}]")

            for s, d in sorted(edges_acyclic):
                md_lines.append(f"    {self._mermaid_id(s)} --> {self._mermaid_id(d)}")

            md_lines.append("```")

            output_file = Path(output_path)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))

            logger.info(f"Wrote dependency tree to {output_file}")

        except Exception as e:
            logger.warning(f"Failed to write dependency tree markdown: {e}")

    def _mermaid_id(self, module_name: str) -> str:
        ident = re.sub(r"[^A-Za-z0-9_]", "_", module_name)
        if not ident or not ident[0].isalpha():
            ident = f"n_{ident}" if ident else "n"
        return ident

    def _would_create_cycle(self, adj: dict[str, set[str]], src: str, dst: str) -> bool:
        if src == dst:
            return True

        seen: set[str] = set()
        stack: list[str] = [dst]

        while stack:
            cur = stack.pop()
            if cur == src:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in adj.get(cur, set()):
                if nxt not in seen:
                    stack.append(nxt)

        return False
