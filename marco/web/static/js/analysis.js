/**
 * Analysis view: real-time binary analysis table with live updates.
 */
var Analysis = (function () {
    "use strict";

    var state = null;

    function init() {
        document.getElementById("analysis-form").addEventListener("submit", onSubmit);
    }

    function onSubmit(e) {
        e.preventDefault();
        var seedRaw = document.getElementById("seed-input").value.trim();
        if (!seedRaw) return;

        var seeds = seedRaw.split(/\s+/);
        var searchPaths = document.getElementById("search-paths-input").value.trim();
        var workers = document.getElementById("workers-input").value;
        var depth = document.getElementById("depth-input").value;

        var body = {
            seed: seeds,
            search_paths: searchPaths ? searchPaths.split(/\s*;\s*/) : [],
            no_kernel: document.getElementById("no-kernel-input").checked,
            single_binary: document.getElementById("single-binary-input").checked,
            prewalk: document.getElementById("prewalk-input").checked,
            use_processes: document.getElementById("use-processes-input").checked,
            load_neo4j: document.getElementById("load-neo4j-input").checked,
        };
        if (workers) body.workers = parseInt(workers, 10);
        if (depth) body.depth = parseInt(depth, 10);

        document.getElementById("analyze-btn").disabled = true;

        fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.error) {
                    alert(data.error);
                    document.getElementById("analyze-btn").disabled = false;
                }
            })
            .catch(function (err) {
                alert("Failed to start analysis: " + err);
                document.getElementById("analyze-btn").disabled = false;
            });
    }

    function updateState(newState) {
        state = newState;
        renderTable();
        updateFooter();
        updateElapsed();
        updatePhase();

        if (state.running) {
            document.getElementById("analyze-btn").disabled = true;
        } else {
            document.getElementById("analyze-btn").disabled = false;
        }
    }

    function handleEvent(event) {
        if (!state) return;

        switch (event.type) {
            case "binary_queued":
                addOrUpdateBinary({ name: event.name, depth: event.depth, status: "queued" });
                break;
            case "binary_started":
                addOrUpdateBinary({ name: event.name, depth: event.depth, status: "analyzing" });
                break;
            case "binary_completed":
                addOrUpdateBinary({
                    name: event.name,
                    depth: event.depth,
                    status: "completed",
                    node_count: event.node_count,
                    edge_count: event.edge_count,
                    import_count: event.import_count,
                    elapsed_s: event.elapsed_s,
                    edge_kind_counts: event.edge_kind_counts || {},
                });
                updateAggregates(event);
                break;
            case "binary_error":
                addOrUpdateBinary({ name: event.name, depth: event.depth, status: "error", error: event.error });
                break;
            case "analysis_complete":
                state.running = false;
                state.elapsed_s = event.elapsed_s;
                state.current_phase = null;
                state.phase_progress = null;
                document.getElementById("analyze-btn").disabled = false;
                updatePhase();
                break;
            case "phase_started":
                state.running = true;
                state.current_phase = event.phase;
                state.phase_progress = null;
                updatePhase();
                break;
            case "phase_progress":
                state.current_phase = event.phase;
                state.phase_progress = [event.current, event.total];
                updatePhase();
                break;
            case "phase_complete":
                if (state.current_phase === event.phase) {
                    state.current_phase = null;
                    state.phase_progress = null;
                }
                updatePhase();
                break;
        }
        renderTable();
        updateFooter();
    }

    function addOrUpdateBinary(entry) {
        if (!state.binaries) state.binaries = [];
        var found = false;
        for (var i = 0; i < state.binaries.length; i++) {
            if (state.binaries[i].name.toLowerCase() === entry.name.toLowerCase()) {
                Object.assign(state.binaries[i], entry);
                found = true;
                break;
            }
        }
        if (!found) {
            state.binaries.push(entry);
            state.running = true;
        }
    }

    function updateAggregates(event) {
        if (!state.aggregates) {
            state.aggregates = { total_nodes: 0, total_edges: 0, total_imports: 0, total_syscalls: 0 };
        }
        state.aggregates.total_nodes += event.node_count || 0;
        state.aggregates.total_edges += event.edge_count || 0;
        state.aggregates.total_imports += event.import_count || 0;
        if (event.edge_kind_counts) {
            state.aggregates.total_syscalls = (state.aggregates.total_syscalls || 0) + (event.edge_kind_counts.SYSCALL || 0);
        }

        if (!state.throughput_history) state.throughput_history = [];
        state.throughput_history.push(Date.now() / 1000);
    }

    function renderTable() {
        var container = document.getElementById("analysis-table-container");
        if (!state || !state.binaries || state.binaries.length === 0) {
            container.innerHTML = "";
            return;
        }

        var html = '<table><thead><tr>';
        html += '<th>binary</th>';
        html += '<th class="num">fn</th>';
        html += '<th class="num">calls</th>';
        html += '<th class="num">imports</th>';
        html += '<th class="num">time</th>';
        html += '<th>info</th>';
        html += '</tr></thead><tbody>';

        for (var i = 0; i < state.binaries.length; i++) {
            var b = state.binaries[i];
            html += renderRow(b);
        }

        html += "</tbody></table>";
        container.innerHTML = html;

        // Attach click handlers for sidenotes
        var rows = container.querySelectorAll("tr[data-binary]");
        for (var j = 0; j < rows.length; j++) {
            rows[j].addEventListener("click", onRowClick);
        }
    }

    function renderRow(b) {
        var cls = "status-" + b.status;
        var indent = (b.depth || 0) * 16;
        var row = '<tr class="' + cls + '" data-binary="' + Table.esc(b.name) + '">';

        // Binary name with depth indentation
        row += '<td class="binary-name">';
        if (indent > 0) {
            row += '<span class="depth-indent" style="width:' + indent + 'px"></span>';
        }
        row += Table.esc(b.name) + "</td>";

        if (b.status === "completed") {
            row += '<td class="num">' + fmtNum(b.node_count) + "</td>";
            row += '<td class="num">' + fmtNum(b.edge_count) + "</td>";
            row += '<td class="num">' + fmtNum(b.import_count) + "</td>";
            row += '<td class="num">' + fmtTime(b.elapsed_s) + "</td>";
            var info = [];
            var ekc = b.edge_kind_counts || {};
            if (ekc.SYSCALL) info.push(fmtNum(ekc.SYSCALL) + " syscalls");
            if (ekc.RPC_CLIENT_CALL) info.push(fmtNum(ekc.RPC_CLIENT_CALL) + " rpc");
            if (ekc.SECURE_CALL) info.push(fmtNum(ekc.SECURE_CALL) + " secure calls");
            row += "<td>" + info.join(", ") + "</td>";
        } else if (b.status === "analyzing") {
            row += '<td class="num"></td>';
            row += '<td class="num"></td>';
            row += '<td class="num"></td>';
            row += '<td class="num" id="timer-' + safeName(b.name) + '">' + fmtTime(b.elapsed_s || 0) + "</td>";
            row += "<td>analyzing</td>";
        } else if (b.status === "queued") {
            row += '<td class="num"></td><td class="num"></td><td class="num"></td><td class="num"></td>';
            row += "<td>queued</td>";
        } else if (b.status === "error") {
            row += '<td class="num"></td><td class="num"></td><td class="num"></td><td class="num"></td>';
            row += "<td>" + Table.esc(b.error || "error") + "</td>";
        }

        row += "</tr>";
        return row;
    }

    function onRowClick(e) {
        var row = e.currentTarget;
        var name = row.getAttribute("data-binary");
        if (!state || !state.binaries) return;

        var b = null;
        for (var i = 0; i < state.binaries.length; i++) {
            if (state.binaries[i].name === name) {
                b = state.binaries[i];
                break;
            }
        }
        if (!b) return;
        showSidenote(b);
    }

    function showSidenote(b) {
        var content = document.getElementById("sidenote-content");
        var html = '<div class="sidenote">';
        html += "<h3>" + Table.esc(b.name) + "</h3>";
        html += "<p>depth: " + b.depth + " &middot; status: " + b.status + "</p>";

        if (b.status === "completed") {
            html += '<table class="detail-table">';
            html += "<tr><td>functions</td><td class='num'>" + fmtNum(b.node_count) + "</td></tr>";
            html += "<tr><td>edges</td><td class='num'>" + fmtNum(b.edge_count) + "</td></tr>";
            html += "<tr><td>imports</td><td class='num'>" + fmtNum(b.import_count) + "</td></tr>";
            html += "<tr><td>elapsed</td><td class='num'>" + fmtTime(b.elapsed_s) + "</td></tr>";

            var ekc = b.edge_kind_counts || {};
            for (var kind in ekc) {
                if (ekc.hasOwnProperty(kind) && ekc[kind] > 0) {
                    html += "<tr><td>" + Table.esc(kind.toLowerCase()) + "</td><td class='num'>" + fmtNum(ekc[kind]) + "</td></tr>";
                }
            }

            html += "</table>";

            if (b.discovered && b.discovered.length > 0) {
                html += '<p style="margin-top:0.5rem;font-weight:600">discovered imports</p>';
                html += '<div class="dep-list">';
                for (var i = 0; i < b.discovered.length; i++) {
                    html += "<span>" + Table.esc(b.discovered[i]) + "</span>";
                }
                html += '</div>';
            }
        } else if (b.status === "error") {
            html += '<p class="query-error">' + Table.esc(b.error || "unknown error") + "</p>";
        }

        html += "</div>";
        content.innerHTML = html;
    }

    function updateFooter() {
        if (!state || !state.binaries || state.binaries.length === 0) {
            document.getElementById("analysis-footer").style.display = "none";
            return;
        }

        document.getElementById("analysis-footer").style.display = "";
        var agg = state.aggregates || {};
        document.getElementById("total-nodes").textContent = fmtNum(agg.total_nodes || 0);
        document.getElementById("total-edges").textContent = fmtNum(agg.total_edges || 0);
        document.getElementById("total-imports").textContent = fmtNum(agg.total_imports || 0);

        var syscalls = agg.total_syscalls || 0;
        var syscallStat = document.getElementById("total-syscalls-stat");
        if (syscalls > 0) {
            document.getElementById("total-syscalls").textContent = fmtNum(syscalls);
            syscallStat.style.display = "";
        } else {
            syscallStat.style.display = "none";
        }

        // Progress
        var completed = 0;
        var total = 0;
        if (state.binaries) {
            total = state.binaries.length;
            for (var i = 0; i < state.binaries.length; i++) {
                if (state.binaries[i].status === "completed" || state.binaries[i].status === "error") {
                    completed++;
                }
            }
        }
        document.getElementById("analysis-progress").textContent = completed + " of " + total;

        // Sparkline
        var sparkContainer = document.getElementById("sparkline-container");
        if (state.throughput_history && state.throughput_history.length >= 2) {
            sparkContainer.innerHTML = Sparkline.fromTimestamps(state.throughput_history);
        }
    }

    function updatePhase() {
        var el = document.getElementById("phase-indicator");
        if (!el) return;

        if (!state || !state.current_phase) {
            el.style.display = "none";
            return;
        }

        el.style.display = "";
        var label = state.current_phase;
        var progress = state.phase_progress;
        var html = label;

        if (progress && progress[1] > 0) {
            var pct = Math.round((progress[0] / progress[1]) * 100);
            html += " " + fmtNum(progress[0]) + " / " + fmtNum(progress[1]);
            html += '<span class="phase-bar"><span class="phase-bar-fill" style="width:' + pct + '%"></span></span>';
        }

        el.innerHTML = html;
    }

    function updateElapsed() {
        var el = document.getElementById("elapsed");
        if (!state || !state.running) {
            if (state && state.elapsed_s) {
                el.textContent = fmtTime(state.elapsed_s);
            }
            return;
        }

        if (state.elapsed_s != null) {
            el.textContent = fmtTime(state.elapsed_s);
        }
    }

    function tick() {
        if (!state || !state.running) return;

        // Update header elapsed
        var el = document.getElementById("elapsed");
        if (state.elapsed_s != null) {
            el.textContent = fmtTime(state.elapsed_s);
        }

        // Update analyzing timers
        if (state.binaries) {
            for (var i = 0; i < state.binaries.length; i++) {
                var b = state.binaries[i];
                if (b.status === "analyzing" && b.elapsed_s != null) {
                    var timerId = "timer-" + safeName(b.name);
                    var timerEl = document.getElementById(timerId);
                    if (timerEl) {
                        b.elapsed_s += 1;
                        timerEl.textContent = fmtTime(b.elapsed_s);
                    }
                }
            }
        }
    }

    function fmtNum(n) {
        if (n == null) return "";
        return Number(n).toLocaleString();
    }

    function fmtTime(s) {
        if (s == null) return "";
        if (s < 60) return s.toFixed(1) + "s";
        var mins = Math.floor(s / 60);
        var secs = s % 60;
        return mins + "m " + secs.toFixed(0) + "s";
    }

    function safeName(name) {
        return name.replace(/[^a-zA-Z0-9]/g, "_");
    }

    return {
        init: init,
        updateState: updateState,
        handleEvent: handleEvent,
        tick: tick,
    };
})();
