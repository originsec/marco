## marco
Cross-binary control-flow cartography

### Features
- **Inter-binary control flow extraction** across traditional `call` edges, as well as syscall, secure call, and RPC client calls
- **Web UI** — browser-based analysis interface with dependency graph visualization and interactive Neo4j query editor
- **Binary Ninja adapter** for binary analysis and extracting function nodes and call edges
- **Module clustering (experimental)** — community detection to group related binaries, with optional LLM-based cluster labeling
- Automatic function name demangling (MSVC and GNU3 formats)
- JSONL export of nodes and edges for external analysis
- Pluggable extractors for additional edges and disassemblers

### Requirements
- Python 3.10+
- Binary Ninja Python API (headless) — see docs: [`https://api.binary.ninja/`](https://api.binary.ninja/)
- Neo4j 5.21.0+ with APOC plugin

### Quick Start
1. Install the Binary Ninja Python API:
```bash
python ~\AppData\Local\Vector35\BinaryNinja\scripts\install_api.py
```

2. Install marco:
```bash
uv tool install git+https://github.com/originsec/marco
```

3. Setup your environment
Marco supports using a persistent config file:
```bash
vim ~/marco.config
# Edit the placeholder values in your editor of choice
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
ANTHROPIC_API_KEY=your_api_key_here (optional, for cluster labeling)
```

Or simply set environment variables:
```bash
$env:NEO4J_URI=neo4j://127.0.0.1:7687
$env:NEO4J_USER=neo4j
$env:NEO4J_PASSWORD=your_password_here
# Optional, for cluster labeling
$env:ANTHROPIC_API_KEY=your_api_key_here
```

4. Run marco
```bash
marco
```
---

### Usage
Running `marco` starts a FastAPI web server — all interaction happens in the browser.

```bash
# Start web UI (opens browser automatically)
marco

# Custom host/port
marco --host 0.0.0.0 --port 8001

# Don't auto-open browser
marco --no-browser

# Custom output directory
marco -o ./results

# With config file
marco --config marco.config
```

### Web UI

The browser interface has three views:

1. **Analysis** — configure and launch analysis runs. Set seed binaries, search paths, worker count, depth limits, and other options. Progress is streamed in real time.
2. **Exploration** — browse results from completed runs. Toggle between a 3D force-directed dependency graph, a tabular module listing, and a module clustering view.
3. **Query** — run Cypher queries against Neo4j with preset templates for common patterns. Results render as tables and/or interactive 3D graphs.

### Performance Tips
- **Process mode** — use the "processes" toggle in the web UI for true parallelism (higher memory)
- **Prewalk** — pre-seed the work queue with PE import tables for better parallel utilization
- **Depth limit** — restrict dependency traversal depth for faster runs
- **No kernel** — skip ntoskrnl.exe/securekernel.exe analysis for user-mode only graphs
- **Binary Ninja tuning** — set `BN_MAX_FUNCTION_SIZE` and `BN_MAX_FUNCTION_UPDATE_COUNT` environment variables for large binaries

### Automatic Dependencies
Marco automatically handles implicit dependencies:
- **ntdll.dll** → automatically queues **ntoskrnl.exe** (syscall target)
- **ntoskrnl.exe** → automatically queues **securekernel.exe** (secure call target)
- **RPC clients** → automatically queues known **RPC server binaries**

### Output Files
Each analysis creates a timestamped directory containing:
- `nodes.jsonl` — all function nodes
- `edges.jsonl` — all function call edges (CALLS, SYSCALL, SECURE_CALL, RPC_CLIENT_CALL, etc.)
- `manifest.json` — analyzed binaries with SHA256 hashes
- `dependencies.md` — Mermaid diagram of module dependencies
- `rpc_registry_final.json` — RPC registry state
- `rpc_unresolved.json` — unresolved RPC edges for debugging
