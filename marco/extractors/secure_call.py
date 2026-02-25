from __future__ import annotations

from ..core.models import Edge, ExtractionResult, Node
from ..disassemblers import DisassemblerAdapter


class SecureCallsExtractor:
    name = "secure_call"

    # Minimal known mapping from NT-side wrappers to Secure Kernel handlers per research.
    # Fallback to the common dispatcher when a specific handler isn't known.
    _KNOWN_HANDLER_BY_WRAPPER = {
        # https://connormcgarr.github.io/secure-images/
        "VslCreateSecureImageSection": "SkmmCreateSecureImageSection",
    }

    def extract(self, *, bv, adapter: DisassemblerAdapter) -> ExtractionResult:
        result = ExtractionResult()
        module = adapter.get_module_name(bv)

        # Secure system calls are only via VslpEnterIumSecureMode in VTL0
        if not module.endswith("ntoskrnl"):
            return result

        # Analyze the Secure Kernel too so the destination appears in the graph
        result.discovered_modules.add("securekernel.exe")

        for fn in adapter.iter_functions(bv):
            src_name = adapter.function_name(fn)
            # Vsl* are the public VTL0 secure-call wrappers. VslpEnterIumSecureMode
            # is the private dispatcher they all funnel through — it only appears in
            # private PDB, so callee-based detection is unreliable. The Vsl* prefix
            # is the correct public-symbol signal.
            if not src_name or not src_name.startswith("Vsl"):
                continue
            if src_name == "VslpEnterIumSecureMode":
                continue

            # Best-effort destination symbol in Secure Kernel
            dst_name = self._KNOWN_HANDLER_BY_WRAPPER.get(src_name, "IumInvokeSecureService")

            src_symbol = f"{module}!{src_name}"
            dst_symbol = f"securekernel!{dst_name}"

            result.edges.append(Edge(src=src_symbol, dst=dst_symbol, kind="SECURE_CALL"))

            # Placeholders for source and destination so they show up even if not analyzed yet
            result.nodes.append(
                Node(
                    symbol=src_symbol,
                    module=module,
                    name=src_name,
                    address=0,
                    kind="function",
                    props={"source": "derived", "placeholder": True},
                )
            )
            result.nodes.append(
                Node(
                    symbol=dst_symbol,
                    module="securekernel",
                    name=dst_name,
                    address=0,
                    kind="function",
                    props={"source": "derived", "placeholder": True},
                )
            )

        return result
