from __future__ import annotations

from ..core.models import Edge, ExtractionResult, Node
from ..disassemblers import DisassemblerAdapter
from ..utils.demangler import add_demangled_property


class CallsExtractor:
    name = "calls"

    def extract(self, *, bv, adapter: DisassemblerAdapter) -> ExtractionResult:
        result = ExtractionResult()

        module = adapter.get_module_name(bv)
        file_version = None
        try:
            file_version = adapter.get_file_version(bv)
        except Exception:
            file_version = None

        # Get arch and platform for demangling
        arch = getattr(bv, "arch", None)
        platform = getattr(bv, "platform", None)

        for fn in adapter.iter_functions(bv):
            fn_name = adapter.function_name(fn)
            symbol = f"{module}!{fn_name}"

            props = {
                "source": "binaryninja",
                "placeholder": False,
                **({"file_version": file_version} if file_version else {}),
            }

            # Add demangled name if applicable
            add_demangled_property(props, fn_name, arch, platform)

            node = Node(
                symbol=symbol,
                module=module,
                name=fn_name,
                address=adapter.function_address(fn),
                kind="function",
                props=props,
            )
            result.nodes.append(node)

            callees = adapter.function_callees_symbols(bv, fn)
            for callee in callees:
                edge = Edge(src=symbol, dst=callee, kind="CALLS")
                result.edges.append(edge)

                # Add placeholder nodes for external callees to pre-populate properties
                # We'll fill the rest of the properties in if/when we see the the function
                # in the binary. If this is a single-shot run, we'll just leave the placeholder
                # so that we can see the external function in the graph.
                if "!" in callee:
                    mod_name, func_name = callee.split("!", 1)
                    placeholder_props = {"source": "import", "placeholder": True}

                    # Try to demangle placeholder names too
                    add_demangled_property(placeholder_props, func_name, arch, platform)

                    placeholder = Node(
                        symbol=callee,
                        module=mod_name,
                        name=func_name,
                        address=0,
                        kind="function",
                        props=placeholder_props,
                    )
                    result.nodes.append(placeholder)

        # Imported modules become new binaries to analyze
        result.discovered_modules.update(adapter.imported_modules(bv))
        return result
