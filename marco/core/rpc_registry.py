"""RPC registry for tracking and resolving client/server relationships."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .models import Edge
from .rpc_models import RPCClientCall, RPCInterface

logger = logging.getLogger(__name__)


@dataclass
class RPCRegistry:
    """Registry for tracking RPC interfaces and resolving client/server edges."""

    interfaces: dict[str, RPCInterface] = field(default_factory=dict)  # interface_id -> RPCInterface
    pending_clients: list[RPCClientCall] = field(default_factory=list)
    resolved_edges: list[Edge] = field(default_factory=list)
    unresolved_edges: list[Edge] = field(default_factory=list)
    _emitted_edges: set[tuple[str, str, str, int]] = field(default_factory=set)

    def register_interface(self, interface: RPCInterface) -> None:
        if interface.interface_id in self.interfaces:
            existing = self.interfaces[interface.interface_id]
            logger.warning(
                f"Interface {interface.interface_id} already registered "
                f"by {existing.server_binary}, overwriting with {interface.server_binary}"
            )

        self.interfaces[interface.interface_id] = interface
        logger.debug(
            f"Registered interface {interface.interface_id} from {interface.server_binary} "
            f"with {len(interface.procedures)} procedures"
        )

        self._resolve_pending_clients()

    def register_client_call(self, client_call: RPCClientCall) -> Edge | None:
        """Resolve immediately if server is known; otherwise queue as pending."""
        edge = self._try_resolve_client(client_call)

        if edge:
            self.resolved_edges.append(edge)
            logger.debug(
                f"Resolved RPC call from {client_call.client_function} to {edge.dst} (OpNum {client_call.opnum})"
            )
            return edge
        else:
            self.pending_clients.append(client_call)
            logger.debug(
                f"Added pending RPC call from {client_call.client_function} "
                f"(interface {client_call.interface_id}, OpNum {client_call.opnum})"
            )

            unresolved_edge = Edge(
                src=client_call.client_function,
                dst=f"UNRESOLVED_RPC_{client_call.interface_id}_{client_call.opnum}",
                kind="RPC_CLIENT_CALL",
                props={
                    "interface_id": client_call.interface_id,
                    "opnum": client_call.opnum,
                    "rpc_api": client_call.rpc_api,
                    "call_address": client_call.call_address,
                    "unresolved": True,
                },
            )
            self.unresolved_edges.append(unresolved_edge)
            return None

    def _try_resolve_client(self, client_call: RPCClientCall) -> Edge | None:
        interface = self.interfaces.get(client_call.interface_id)
        if not interface:
            return None

        procedure = interface.procedures.get(client_call.opnum)
        if not procedure:
            logger.warning(f"Interface {client_call.interface_id} found but OpNum {client_call.opnum} not registered")
            return None

        edge = Edge(
            src=client_call.client_function,
            dst=procedure.symbol,
            kind="RPC_CLIENT_CALL",
            props={
                "interface_id": client_call.interface_id,
                "opnum": client_call.opnum,
                "client_api": client_call.rpc_api,
                "server_api": interface.registration_api,
                "call_address": client_call.call_address,
                "server_address": procedure.address,
            },
        )

        return edge

    def _resolve_pending_clients(self) -> None:
        newly_resolved = []
        still_pending = []

        for client_call in self.pending_clients:
            edge = self._try_resolve_client(client_call)
            if edge:
                newly_resolved.append(edge)
                logger.debug(f"Resolved pending RPC call from {client_call.client_function} to {edge.dst}")

                self.unresolved_edges = [
                    e
                    for e in self.unresolved_edges
                    if not (
                        e.src == client_call.client_function
                        and e.props.get("interface_id") == client_call.interface_id
                        and e.props.get("opnum") == client_call.opnum
                    )
                ]
            else:
                still_pending.append(client_call)

        self.resolved_edges.extend(newly_resolved)
        self.pending_clients = still_pending

        if newly_resolved:
            logger.debug(f"Resolved {len(newly_resolved)} pending RPC calls")

    def get_all_edges(self, final: bool = False) -> list[Edge]:
        """
        Return newly resolved edges not yet emitted. If final=True, also include still-unresolved edges.
        Deduplicates by (src, dst, kind, opnum).
        """
        edges_to_return = []

        for edge in self.resolved_edges:
            opnum = edge.props.get("opnum", -1)
            edge_key = (edge.src, edge.dst, edge.kind, opnum if isinstance(opnum, int) else -1)
            if edge_key not in self._emitted_edges:
                edges_to_return.append(edge)
                self._emitted_edges.add(edge_key)

        if final:
            for unresolved in self.unresolved_edges:
                opnum = unresolved.props.get("opnum", -1)
                edge_key = (unresolved.src, unresolved.dst, unresolved.kind, opnum if isinstance(opnum, int) else -1)
                if edge_key not in self._emitted_edges:
                    edges_to_return.append(unresolved)
                    self._emitted_edges.add(edge_key)

        return edges_to_return

    def get_statistics(self) -> dict:
        return {
            "registered_interfaces": len(self.interfaces),
            "total_procedures": sum(len(i.procedures) for i in self.interfaces.values()),
            "pending_clients": len(self.pending_clients),
            "resolved_edges": len(self.resolved_edges),
            "unresolved_edges": len(self.unresolved_edges),
            "interfaces_by_module": self._get_interfaces_by_module(),
        }

    def _get_interfaces_by_module(self) -> dict[str, list[str]]:
        by_module = {}
        for interface in self.interfaces.values():
            if interface.server_binary not in by_module:
                by_module[interface.server_binary] = []
            by_module[interface.server_binary].append(interface.interface_id)
        return by_module

    def save_to_file(self, filepath: Path) -> None:
        data = {
            "interfaces": {
                iid: {
                    "interface_id": iface.interface_id,
                    "server_binary": iface.server_binary,
                    "registration_function": iface.registration_function,
                    "registration_api": iface.registration_api,
                    "structure_address": iface.structure_address,
                    "procedures": {
                        str(opnum): {
                            "opnum": proc.opnum,
                            "address": proc.address,
                            "symbol": proc.symbol,
                            "function_name": proc.function_name,
                        }
                        for opnum, proc in iface.procedures.items()
                    },
                }
                for iid, iface in self.interfaces.items()
            },
            "pending_clients": [
                {
                    "client_function": cc.client_function,
                    "client_address": cc.client_address,
                    "call_address": cc.call_address,
                    "interface_id": cc.interface_id,
                    "opnum": cc.opnum,
                    "rpc_api": cc.rpc_api,
                }
                for cc in self.pending_clients
            ],
            "emitted_edges": [list(key) for key in self._emitted_edges],
            "statistics": self.get_statistics(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.debug(f"Saved RPC registry to {filepath}")

    @classmethod
    def load_from_file(cls, filepath: Path) -> RPCRegistry:
        if not filepath.exists():
            logger.warning(f"Registry file {filepath} not found, creating new registry")
            return cls()

        try:
            with open(filepath) as f:
                data = json.load(f)

            registry = cls()

            for iid, iface_data in data.get("interfaces", {}).items():
                from .rpc_models import RPCInterface, RPCProcedure

                procedures = {}
                for opnum_str, proc_data in iface_data.get("procedures", {}).items():
                    proc = RPCProcedure(
                        opnum=proc_data["opnum"],
                        address=proc_data["address"],
                        symbol=proc_data["symbol"],
                        function_name=proc_data["function_name"],
                    )
                    procedures[int(opnum_str)] = proc

                interface = RPCInterface(
                    interface_id=iface_data["interface_id"],
                    server_binary=iface_data["server_binary"],
                    registration_function=iface_data["registration_function"],
                    registration_api=iface_data["registration_api"],
                    procedures=procedures,
                    structure_address=iface_data.get("structure_address", 0),
                )
                registry.interfaces[iid] = interface

            for cc_data in data.get("pending_clients", []):
                from .rpc_models import RPCClientCall

                client_call = RPCClientCall(
                    client_function=cc_data["client_function"],
                    client_address=cc_data["client_address"],
                    call_address=cc_data["call_address"],
                    interface_id=cc_data["interface_id"],
                    opnum=cc_data["opnum"],
                    rpc_api=cc_data["rpc_api"],
                )
                registry.pending_clients.append(client_call)

            for edge_key_list in data.get("emitted_edges", []):
                if len(edge_key_list) == 4:
                    registry._emitted_edges.add(tuple(edge_key_list))

            logger.debug(
                f"Loaded RPC registry from {filepath} "
                f"({len(registry.interfaces)} interfaces, "
                f"{len(registry.pending_clients)} pending clients, "
                f"{len(registry._emitted_edges)} emitted edges)"
            )

            registry._resolve_pending_clients()

            return registry

        except Exception as e:
            logger.error(f"Failed to load registry from {filepath}: {e}")
            return cls()

    def export_unresolved_edges(self, filepath: Path) -> None:
        unresolved_data = []

        for client_call in self.pending_clients:
            unresolved_data.append(
                {
                    "client_function": client_call.client_function,
                    "interface_id": client_call.interface_id,
                    "opnum": client_call.opnum,
                    "rpc_api": client_call.rpc_api,
                    "known_interface": client_call.interface_id in self.interfaces,
                    "interface_procedures": (
                        list(self.interfaces[client_call.interface_id].procedures.keys())
                        if client_call.interface_id in self.interfaces
                        else []
                    ),
                }
            )

        with open(filepath, "w") as f:
            json.dump(unresolved_data, f, indent=2)

        logger.debug(f"Exported {len(unresolved_data)} unresolved edges to {filepath}")
