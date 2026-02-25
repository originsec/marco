/**
 * Exploration view: graph + table dependency views.
 *
 * Each module appears exactly once. Graph is the default view.
 * Click a node or row for sidenote detail with full import/imported-by lists.
 */
var Exploration = (function () {
    "use strict";

    var currentData = null;
    var sortField = "depth";
    var sortAsc = true;
    var viewMode = "graph";

    // Numeric fields default to descending on first click
    var NUMERIC_FIELDS = { depth: false, functions: true, edges: true, xmod: true, imports: true, imported_by: true };

    function init() {
        // No dropdown listener needed — headers handle sorting
    }

    function setViewMode(mode) {
        viewMode = mode;

        var graphContainer = document.getElementById("explore-graph-container");
        var tableContainer = document.getElementById("explore-table-container");
        var summaryDiv = document.getElementById("explore-table-summary");
        var clusterContainer = document.getElementById("cluster-graph-container");
        var clusterStatus = document.getElementById("cluster-status");

        if (mode === "graph") {
            if (graphContainer) graphContainer.style.display = "";
            if (tableContainer) tableContainer.style.display = "none";
            if (summaryDiv) summaryDiv.style.display = "none";
            if (clusterContainer) clusterContainer.style.display = "none";
            if (clusterStatus) clusterStatus.style.display = "none";
        } else if (mode === "clusters") {
            if (graphContainer) graphContainer.style.display = "none";
            if (tableContainer) tableContainer.style.display = "none";
            if (summaryDiv) summaryDiv.style.display = "none";
            if (clusterContainer) clusterContainer.style.display = "";
        } else {
            if (graphContainer) graphContainer.style.display = "none";
            if (tableContainer) tableContainer.style.display = "";
            if (summaryDiv) summaryDiv.style.display = "";
            if (clusterContainer) clusterContainer.style.display = "none";
            if (clusterStatus) clusterStatus.style.display = "none";
        }

        // Constrain sidenote height to match graph viewport in clusters mode
        var sidenote = document.querySelector(".sidenote-column");
        if (sidenote) {
            if (mode === "clusters" && clusterContainer) {
                // Defer until container is visible and has layout
                setTimeout(function () {
                    var h = clusterContainer.offsetHeight;
                    if (h > 0) sidenote.style.maxHeight = h + "px";
                }, 0);
            } else {
                sidenote.style.maxHeight = "";
            }
        }

        // Update toggle buttons
        var buttons = document.querySelectorAll("#explore-view-toggle .toggle-btn");
        for (var i = 0; i < buttons.length; i++) {
            if (buttons[i].getAttribute("data-mode") === mode) {
                buttons[i].classList.add("active");
            } else {
                buttons[i].classList.remove("active");
            }
        }

        renderCurrentView();
    }

    function renderCurrentView() {
        if (viewMode === "graph") {
            if (typeof DepGraph !== "undefined" && currentData) {
                DepGraph.resize();
                DepGraph.update(currentData);
            }
        } else if (viewMode === "clusters") {
            if (typeof Clusters !== "undefined") {
                Clusters.load(currentData);
            }
        } else {
            renderTable();
        }
    }

    function load() {
        fetch("/api/dependency-graph")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                currentData = enrichData(data);
                renderCurrentView();
            })
            .catch(function () {
                var container = document.getElementById("explore-table-container");
                container.innerHTML = '<p class="empty-state">Failed to load dependency data.</p>';
            });
    }

    function updateFromState(state) {
        if (!state || !state.binaries || state.binaries.length === 0) return;

        var modules = [];
        var edges = [];

        for (var i = 0; i < state.binaries.length; i++) {
            var b = state.binaries[i];
            modules.push({
                name: b.name,
                depth: b.depth,
                status: b.status,
                node_count: b.node_count || 0,
                edge_count: b.edge_count || 0,
                edge_kind_counts: b.edge_kind_counts || {},
                xmod_edge_count: b.xmod_edge_count || 0,
            });

            if (b.discovered) {
                for (var j = 0; j < b.discovered.length; j++) {
                    edges.push({ source: b.name.toLowerCase(), target: b.discovered[j].toLowerCase() });
                }
            }
        }

        currentData = enrichData({ modules: modules, edges: edges });
    }

    /** Compute imports/imported-by lists for each module. */
    function enrichData(data) {
        if (!data || !data.modules) return data;

        var modules = data.modules;
        var edges = data.edges || [];

        // Build lookup
        var byName = {};
        for (var i = 0; i < modules.length; i++) {
            var key = modules[i].name.toLowerCase();
            byName[key] = modules[i];
            modules[i]._imports = [];
            modules[i]._importedBy = [];
        }

        // Populate relationship lists
        for (var e = 0; e < edges.length; e++) {
            var src = edges[e].source;
            var dst = edges[e].target;
            if (byName[src]) byName[src]._imports.push(dst);
            if (byName[dst]) byName[dst]._importedBy.push(src);
        }

        return data;
    }

    function renderTable() {
        var container = document.getElementById("explore-table-container");
        var summaryDiv = document.getElementById("explore-table-summary");

        if (!currentData || !currentData.modules || currentData.modules.length === 0) {
            container.innerHTML = '<p class="empty-state">Run an analysis to explore dependencies.</p>';
            if (summaryDiv) summaryDiv.style.display = "none";
            return;
        }

        var modules = currentData.modules.slice();
        sortModules(modules);

        // Compute maxes for data bars
        var maxFn = 0, maxEdges = 0, maxXmod = 0;
        var totalFn = 0, totalEdges = 0, analyzed = 0;
        var depthSet = {};
        for (var j = 0; j < modules.length; j++) {
            var nc = modules[j].node_count || 0;
            var ec = modules[j].edge_count || 0;
            var xc = modules[j].xmod_edge_count || 0;
            if (nc > maxFn) maxFn = nc;
            if (ec > maxEdges) maxEdges = ec;
            if (xc > maxXmod) maxXmod = xc;
            totalFn += nc;
            totalEdges += ec;
            depthSet[modules[j].depth || 0] = true;
            if (modules[j].status === "completed") analyzed++;
        }
        var depthLevels = Object.keys(depthSet).length;

        // Summary line
        if (summaryDiv) {
            summaryDiv.textContent = fmtNum(modules.length) + " modules \u00b7 " +
                depthLevels + " depth level" + (depthLevels !== 1 ? "s" : "") + " \u00b7 " +
                fmtNum(totalFn) + " functions \u00b7 " +
                fmtNum(totalEdges) + " edges";
            summaryDiv.style.display = "";
        }

        // Column definitions: [label, sortKey, isNumeric]
        var cols = [
            ["d", "depth", true],
            ["module", "name", false],
            ["fn", "functions", true],
            ["edges", "edges", true],
            ["xmod", "xmod", true],
            ["imports", "imports", true],
            ["imp.\u00a0by", "imported_by", true],
        ];

        var html = '<table><thead><tr>';
        for (var c = 0; c < cols.length; c++) {
            var col = cols[c];
            var thClass = col[2] ? "num" : "";
            if (col[1]) {
                thClass += (thClass ? " " : "") + "sortable";
                var indicator = "";
                if (sortField === col[1]) {
                    indicator = ' <span class="sort-indicator">' + (sortAsc ? "\u25b2" : "\u25bc") + '</span>';
                }
                html += '<th class="' + thClass + '" data-sort="' + col[1] + '">' + col[0] + indicator + '</th>';
            } else {
                html += '<th class="' + thClass + '">' + col[0] + '</th>';
            }
        }
        html += '</tr></thead><tbody>';

        for (var i = 0; i < modules.length; i++) {
            html += renderRow(modules[i], maxFn, maxEdges, maxXmod);
        }

        html += '</tbody></table>';
        container.innerHTML = html;

        // Attach header click handlers
        var headers = container.querySelectorAll("th.sortable");
        for (var h = 0; h < headers.length; h++) {
            headers[h].addEventListener("click", onHeaderClick);
        }

        // Attach row click handlers
        var rows = container.querySelectorAll("tr[data-binary]");
        for (var k = 0; k < rows.length; k++) {
            rows[k].addEventListener("click", onRowClick);
        }
    }

    function renderRow(mod, maxFn, maxEdges, maxXmod) {
        var isCompleted = mod.status === "completed";
        var row = '<tr data-binary="' + Table.esc(mod.name) + '">';

        // Depth
        row += '<td class="num">' + (mod.depth || 0) + '</td>';

        // Module name with optional status suffix
        row += '<td class="binary-name">' + Table.esc(mod.name);
        if (!isCompleted) {
            row += '<span class="status-suffix">' + Table.esc(mod.status) + '</span>';
        }
        row += '</td>';

        if (isCompleted) {
            // fn with data bar
            row += renderBarCell(mod.node_count, maxFn);
            // edges with data bar
            row += renderBarCell(mod.edge_count, maxEdges);
            // xmod (inter-binary edges) with data bar
            row += renderBarCell(mod.xmod_edge_count || 0, maxXmod);

            // Imports count
            var imports = mod._imports || [];
            row += '<td class="num">' + imports.length + '</td>';

            // Imported-by count
            var importedBy = mod._importedBy || [];
            row += '<td class="num">' + importedBy.length + '</td>';
        } else {
            row += '<td class="num"></td><td class="num"></td><td class="num"></td>';
            row += '<td class="num"></td><td class="num"></td>';
        }

        row += '</tr>';
        return row;
    }

    function renderBarCell(value, max) {
        var pct = max > 0 ? (value / max) * 100 : 0;
        return '<td class="num bar-cell">' +
            '<span class="bar-fill" style="width:' + pct.toFixed(1) + '%"></span>' +
            '<span class="bar-value">' + fmtNum(value) + '</span>' +
            '</td>';
    }

    function onHeaderClick(e) {
        var field = e.currentTarget.getAttribute("data-sort");
        if (!field) return;

        if (sortField === field) {
            // Toggle direction on re-click
            sortAsc = !sortAsc;
        } else {
            sortField = field;
            // Numeric columns default descending, text columns default ascending
            sortAsc = !NUMERIC_FIELDS[field];
        }

        renderTable();
    }

    function onRowClick(e) {
        var name = e.currentTarget.getAttribute("data-binary");
        showSidenote(name);
    }

    function showSidenote(name) {
        if (!currentData) return;

        var mod = null;
        for (var i = 0; i < currentData.modules.length; i++) {
            if (currentData.modules[i].name.toLowerCase() === name.toLowerCase()) {
                mod = currentData.modules[i];
                break;
            }
        }

        var content = document.getElementById("sidenote-content");
        var html = '<div class="sidenote">';
        html += '<h3>' + Table.esc(name) + '</h3>';

        if (mod && mod.status === "completed") {
            html += '<table class="detail-table">';
            html += '<tr><td>functions</td><td class="num">' + fmtNum(mod.node_count) + '</td></tr>';
            html += '<tr><td>edges</td><td class="num">' + fmtNum(mod.edge_count) + '</td></tr>';
            html += '<tr><td>depth</td><td class="num">' + mod.depth + '</td></tr>';

            var ekc = mod.edge_kind_counts || {};
            for (var kind in ekc) {
                if (ekc.hasOwnProperty(kind) && ekc[kind] > 0) {
                    html += '<tr><td>' + Table.esc(kind.toLowerCase()) + '</td><td class="num">' + fmtNum(ekc[kind]) + '</td></tr>';
                }
            }
            html += '</table>';

            // Full imports list
            var imports = mod._imports || [];
            if (imports.length > 0) {
                html += '<p style="margin-top:0.5rem;font-weight:600">imports (' + imports.length + ')</p>';
                html += '<div class="dep-list">';
                for (var j = 0; j < imports.length; j++) {
                    var isAnalyzed = isModuleAnalyzed(imports[j]);
                    html += '<span class="' + (isAnalyzed ? '' : 'not-analyzed') + '">' + Table.esc(imports[j]) + '</span>';
                }
                html += '</div>';
            }

            // Full imported-by list
            var importedBy = mod._importedBy || [];
            if (importedBy.length > 0) {
                html += '<p style="margin-top:0.5rem;font-weight:600">imported by (' + importedBy.length + ')</p>';
                html += '<div class="dep-list">';
                for (var k = 0; k < importedBy.length; k++) {
                    html += '<span>' + Table.esc(importedBy[k]) + '</span>';
                }
                html += '</div>';
            }
        } else if (mod && mod.status === "error") {
            html += '<p>depth: ' + mod.depth + '</p>';
            html += '<p class="query-error">' + Table.esc(mod.error || "error") + '</p>';
        } else {
            html += '<p class="empty-state">Not analyzed</p>';
        }

        html += '</div>';
        content.innerHTML = html;
    }

    function isModuleAnalyzed(name) {
        if (!currentData || !currentData.modules) return false;
        for (var i = 0; i < currentData.modules.length; i++) {
            if (currentData.modules[i].name.toLowerCase() === name.toLowerCase() &&
                currentData.modules[i].status === "completed") {
                return true;
            }
        }
        return false;
    }

    function sortModules(modules) {
        modules.sort(function (a, b) {
            var va, vb, cmp;
            switch (sortField) {
                case "name":
                    va = a.name.toLowerCase();
                    vb = b.name.toLowerCase();
                    cmp = va < vb ? -1 : va > vb ? 1 : 0;
                    return sortAsc ? cmp : -cmp;
                case "depth":
                    va = a.depth || 0;
                    vb = b.depth || 0;
                    cmp = va - vb;
                    break;
                case "functions":
                    va = a.node_count || 0;
                    vb = b.node_count || 0;
                    cmp = va - vb;
                    break;
                case "edges":
                    va = a.edge_count || 0;
                    vb = b.edge_count || 0;
                    cmp = va - vb;
                    break;
                case "xmod":
                    va = a.xmod_edge_count || 0;
                    vb = b.xmod_edge_count || 0;
                    cmp = va - vb;
                    break;
                case "imports":
                    va = (a._imports || []).length;
                    vb = (b._imports || []).length;
                    cmp = va - vb;
                    break;
                case "imported_by":
                    va = (a._importedBy || []).length;
                    vb = (b._importedBy || []).length;
                    cmp = va - vb;
                    break;
                default:
                    return 0;
            }
            // Primary sort
            var result = sortAsc ? cmp : -cmp;
            // Secondary sort by name for stability
            if (result === 0) {
                var na = a.name.toLowerCase();
                var nb = b.name.toLowerCase();
                return na < nb ? -1 : na > nb ? 1 : 0;
            }
            return result;
        });
    }

    function fmtNum(n) {
        if (n == null) return "";
        return Number(n).toLocaleString();
    }

    return {
        init: init,
        load: load,
        updateFromState: updateFromState,
        renderTable: renderTable,
        renderCurrentView: renderCurrentView,
        setViewMode: setViewMode,
        showSidenote: showSidenote,
    };
})();
