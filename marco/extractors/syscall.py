from __future__ import annotations

import logging

from ..core.models import Edge, ExtractionResult, Node
from ..disassemblers import DisassemblerAdapter

logger = logging.getLogger(__name__)


class SyscallsExtractor:
    name = "syscall"

    def _get_syscall_info(self, bv, adapter: DisassemblerAdapter, fn) -> tuple[bool, int | None]:
        """Return (True, syscall_number) if the function contains a syscall instruction, else (False, None)."""
        try:
            instructions = list(adapter.iter_instructions(fn))

            syscall_idx = -1
            for i, instruction_tuple in enumerate(instructions):
                # Unpack the tuple
                if len(instruction_tuple) != 3:
                    continue
                addr, size, tokens = instruction_tuple

                # Convert tokens to text
                if not tokens or not isinstance(tokens, list):
                    continue

                text_parts = [token.text for token in tokens if hasattr(token, "text")]
                instruction_text = "".join(text_parts).lower()

                # Check for syscall instruction
                if "syscall" in instruction_text:
                    syscall_idx = i
                    break

            if syscall_idx == -1 or not isinstance(syscall_idx, int):
                return (False, None)

            for i in range(syscall_idx - 1, max(0, syscall_idx - 10), -1):
                addr, size, tokens = instructions[i]

                syscall_num = None
                text_parts = []

                for token in tokens:
                    if hasattr(token, "text"):
                        text_parts.append(token.text)

                    # Look for integer tokens which might be the syscall number
                    # Type 4 and 5 are integer constants
                    # We want small integers (syscall numbers are typically < 0x1000)
                    if (
                        hasattr(token, "value")
                        and hasattr(token, "type")
                        and token.type in (4, 5)
                        and 0 <= token.value < 0x1000
                    ):
                        syscall_num = token.value

                instruction_text = "".join(text_parts).lower()

                # Check if this is a "mov eax, <number>" instruction
                if "mov" in instruction_text and "eax" in instruction_text and syscall_num is not None:
                    return (True, syscall_num)

            # Found syscall but couldn't extract number
            return (True, None)

        except Exception as e:
            # If we can't analyze the function, assume it's not a syscall
            logger.debug(f"Error analyzing function for syscall: {e}")
            return (False, None)

    def extract(self, *, bv, adapter: DisassemblerAdapter) -> ExtractionResult:
        """
        Synthetically map ntdll exports Nt*/Zw* to ntoskrnl Nt* entries (SSDT-style),
        independent of actual control-flow, mirroring the old approach.
        """
        result = ExtractionResult()
        module = adapter.get_module_name(bv)

        if not module.endswith("ntdll"):
            return result

        # Since a system call is a transition into the kernel, we'll manually add it
        # to the discovered modules list so that we can analyze it later, which will
        # allow us to see the kernel-side function in the graph.
        result.discovered_modules.add("ntoskrnl.exe")

        syscall_count = 0
        for fn in adapter.iter_functions(bv):
            name = adapter.function_name(fn)
            if not name or not (name.startswith("Nt") or name.startswith("Zw")):
                continue

            # Verify this function actually contains a syscall instruction and get syscall number
            is_syscall, syscall_num = self._get_syscall_info(bv, adapter, fn)
            if not is_syscall:
                continue

            syscall_count += 1

            # Source stub in ntdll
            src_symbol = f"{module}!{name}"
            # Destination kernel "export" (normalize Zw* -> Nt*)
            dst_name = name if name.startswith("Nt") else f"Nt{name[2:]}"
            dst_symbol = f"ntoskrnl!{dst_name}"

            edge_props = {}
            if syscall_num is not None:
                edge_props["syscall_number"] = syscall_num

            result.edges.append(Edge(src=src_symbol, dst=dst_symbol, kind="SYSCALL", props=edge_props))

            # Placeholders for source and destination to ensure nodes exist early.
            # We'll file these the rest of the way in when we process the ntoskrnl
            # later.
            result.nodes.append(
                Node(
                    symbol=src_symbol,
                    module=module,
                    name=name,
                    address=0,
                    kind="function",
                    props={"source": "derived", "placeholder": True},
                )
            )
            result.nodes.append(
                Node(
                    symbol=dst_symbol,
                    module="ntoskrnl",
                    name=dst_name,
                    address=0,
                    kind="function",
                    props={"source": "derived", "placeholder": True},
                )
            )

        if syscall_count > 0:
            logger.info(f"Found {syscall_count} syscall stubs in {module}")

        return result
