from __future__ import annotations

import colorsys
import hashlib
import json
import logging
import time
from collections.abc import Callable

from neo4j import GraphDatabase

logging.getLogger("neo4j").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

NEO4J_BATCH_SIZE = 1000


class Neo4jLoader:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=10,
            connection_acquisition_timeout=10,
        )
        self._validate()

    @staticmethod
    def verify_connection(uri: str, user: str, password: str) -> None:
        driver = None
        try:
            driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=10,
                connection_acquisition_timeout=10,
            )
            with driver.session() as session:
                session.run("RETURN 1").consume()
        except Exception as e:
            raise SystemExit(f"Neo4j connection failed ({type(e).__name__}): {e}") from e
        finally:
            if driver:
                driver.close()

    @staticmethod
    def _sanitize_for_neo4j(value):
        min_i64 = -(2**63)
        max_i64 = (2**63) - 1

        if isinstance(value, int):
            if value < min_i64 or value > max_i64:
                return str(value)
            return value
        if isinstance(value, list):
            return [Neo4jLoader._sanitize_for_neo4j(v) for v in value]
        if isinstance(value, dict):
            return {k: Neo4jLoader._sanitize_for_neo4j(v) for k, v in value.items()}
        return value

    def _validate(self) -> None:
        with self._driver.session() as session:
            session.run("RETURN 1")

    def close(self):
        self._driver.close()

    def _ensure_indexes(self):
        with self._driver.session() as session:
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.symbol)")

    def load_jsonl(
        self,
        nodes_path: str,
        edges_path: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> None:
        self._ensure_indexes()

        with open(nodes_path, encoding="utf-8") as f:
            node_count = sum(1 for line in f if line.strip())
        with open(edges_path, encoding="utf-8") as f:
            edge_count = sum(1 for line in f if line.strip())
        total = node_count + edge_count

        processed = 0

        with self._driver.session() as session:
            with open(nodes_path, encoding="utf-8") as nf:
                batch = []
                for line in nf:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    row = self._sanitize_for_neo4j(row)
                    batch.append(row)
                    if len(batch) >= NEO4J_BATCH_SIZE:
                        self._ingest_nodes(session, batch)
                        processed += len(batch)
                        batch = []
                        if progress_callback:
                            progress_callback("neo4j", processed, total)
                        time.sleep(0)  # yield GIL
                if batch:
                    self._ingest_nodes(session, batch)
                    processed += len(batch)
                    if progress_callback:
                        progress_callback("neo4j", processed, total)
                    time.sleep(0)

            with open(edges_path, encoding="utf-8") as ef:
                batch = []
                for line in ef:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    row = self._sanitize_for_neo4j(row)
                    batch.append(row)
                    if len(batch) >= NEO4J_BATCH_SIZE:
                        self._ingest_edges(session, batch)
                        processed += len(batch)
                        batch = []
                        if progress_callback:
                            progress_callback("neo4j", processed, total)
                        time.sleep(0)
                if batch:
                    self._ingest_edges(session, batch)
                    processed += len(batch)
                    if progress_callback:
                        progress_callback("neo4j", processed, total)
                    time.sleep(0)

    def _ingest_nodes(self, session, batch):
        for row in batch:
            try:
                module = (row.get("module") or "").lower()
                if module and not row.get("color"):
                    row["color"] = self._color_for_module(module)
            except Exception:
                logger.debug("Failed to compute color for node %s", row.get("symbol", "?"), exc_info=True)
        query = (
            "UNWIND $rows AS row "
            "MERGE (n:Function {symbol: row.symbol}) "
            "SET n.module = row.module, n.name = row.name, n.address = row.address, n.kind = row.kind, n += row.props, n.color = coalesce(n.color, row.color)"
        )
        session.run(query, rows=batch)

    def _ingest_edges(self, session, batch):
        by_kind: dict[str, list] = {}
        for row in batch:
            by_kind.setdefault(row["kind"], []).append(row)

        for kind, rows in by_kind.items():
            safe_kind = "".join(c if c.isalnum() or c == "_" else "_" for c in kind)
            query = (
                f"UNWIND $rows AS row "
                f"MERGE (s:Function {{symbol: row.src}}) "
                f"MERGE (d:Function {{symbol: row.dst}}) "
                f"MERGE (s)-[r:{safe_kind}]->(d) "
                f"SET r += row.props"
            )
            session.run(query, rows=rows)

    def query(self, cypher: str, *, parameters: dict | None = None):
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, parameters=parameters or {})]  # type: ignore[arg-type]

    def _color_for_module(self, module: str) -> str:
        hv = int(hashlib.md5(module.encode("utf-8")).hexdigest()[:8], 16)
        hue = (hv % 360) / 360.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
