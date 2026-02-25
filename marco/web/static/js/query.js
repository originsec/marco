/**
 * Query view: Cypher editor, result tables/graph, presets, history.
 */
var Query = (function () {
    "use strict";

    var HISTORY_KEY = "marco_query_history";
    var MAX_HISTORY = 20;
    var graph = null;
    var graphData = null;
    var viewMode = "table";

    var LABEL_COLORS = [
        "#2b2d42", "#658a65", "#c49a3c", "#a86262",
        "#5e6472", "#6a5acd", "#2e8b57", "#cd853f",
    ];
    var labelColorMap = {};
    var labelColorIdx = 0;

    function labelColor(label) {
        if (!labelColorMap[label]) {
            labelColorMap[label] = LABEL_COLORS[labelColorIdx % LABEL_COLORS.length];
            labelColorIdx++;
        }
        return labelColorMap[label];
    }

    function init() {
        document.getElementById("query-run-btn").addEventListener("click", runQuery);

        var textarea = document.getElementById("cypher-input");
        textarea.addEventListener("keydown", function (e) {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                runQuery();
            }
        });

        var presets = document.querySelectorAll("[data-cypher]");
        for (var i = 0; i < presets.length; i++) {
            presets[i].addEventListener("click", function (e) {
                e.preventDefault();
                document.getElementById("cypher-input").value = this.getAttribute("data-cypher");
                runQuery();
            });
        }

        var toggleBtns = document.querySelectorAll("#query-view-toggle .toggle-btn");
        for (var j = 0; j < toggleBtns.length; j++) {
            toggleBtns[j].addEventListener("click", function () {
                setViewMode(this.getAttribute("data-mode"));
            });
        }

        window.addEventListener("resize", onResize);
        checkNeo4jStatus();
    }

    function setViewMode(mode) {
        viewMode = mode;
        var graphContainer = document.getElementById("query-graph-container");
        var resultsEl = document.getElementById("query-results");

        if (mode === "graph") {
            graphContainer.style.display = "";
            resultsEl.style.display = "none";
            renderGraph();
        } else {
            graphContainer.style.display = "none";
            resultsEl.style.display = "";
        }

        var buttons = document.querySelectorAll("#query-view-toggle .toggle-btn");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].classList.toggle("active", buttons[i].getAttribute("data-mode") === mode);
        }
    }

    function onResize() {
        if (viewMode !== "graph" || !graph) return;
        var container = document.getElementById("query-graph-container");
        if (!container) return;
        var w = container.clientWidth;
        var h = container.clientHeight;
        if (w > 0 && h > 0) graph.width(w).height(h);
    }

    function runQuery() {
        var textarea = document.getElementById("cypher-input");
        var cypher = textarea.value.trim();
        if (!cypher) return;

        var statusEl = document.getElementById("query-status");
        var errorEl = document.getElementById("query-error");
        var resultsEl = document.getElementById("query-results");
        var toggleEl = document.getElementById("query-view-toggle");

        statusEl.textContent = "running...";
        errorEl.innerHTML = "";
        resultsEl.innerHTML = "";
        toggleEl.style.display = "none";
        destroyGraph();
        graphData = null;

        var startTime = Date.now();

        fetch("/api/neo4j/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cypher: cypher }),
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

                if (data.error) {
                    statusEl.textContent = "";
                    errorEl.innerHTML = '<div class="query-error">' + Table.esc(data.error) + "</div>";
                    return;
                }

                var columns = data.columns || [];
                var rows = data.rows || [];
                statusEl.textContent = rows.length + " rows in " + elapsed + "s";

                if (rows.length === 0) {
                    resultsEl.innerHTML = '<p class="empty-state">No results.</p>';
                } else {
                    var numeric = [];
                    for (var c = 0; c < columns.length; c++) {
                        var allNum = true;
                        for (var r = 0; r < Math.min(rows.length, 10); r++) {
                            if (rows[r][c] !== null && typeof rows[r][c] !== "number") {
                                allNum = false;
                                break;
                            }
                        }
                        numeric.push(allNum);
                    }
                    resultsEl.innerHTML = Table.render(columns, rows, { numeric: numeric });
                }

                if (data.graph && data.graph.nodes && data.graph.nodes.length > 0) {
                    graphData = data.graph;
                    toggleEl.style.display = "";
                    setViewMode("graph");
                } else {
                    setViewMode("table");
                }

                saveHistory(cypher);
            })
            .catch(function (err) {
                statusEl.textContent = "";
                errorEl.innerHTML = '<div class="query-error">Request failed: ' + Table.esc(err.message) + "</div>";
            });
    }

    function destroyGraph() {
        if (graph) {
            graph._destructor();
            graph = null;
        }
    }

    function renderGraph() {
        if (!graphData) return;

        var container = document.getElementById("query-graph-container");
        if (!container) return;
        var w = container.clientWidth;
        var h = container.clientHeight;
        if (w === 0 || h === 0) return;

        destroyGraph();
        labelColorMap = {};
        labelColorIdx = 0;

        var nodeMap = {};
        var nodes = graphData.nodes.map(function (n) {
            var node = { id: n.id, name: n.name, labels: n.labels, properties: n.properties, _degree: 0 };
            nodeMap[n.id] = node;
            return node;
        });

        var links = graphData.links.map(function (l) {
            if (nodeMap[l.source]) nodeMap[l.source]._degree++;
            if (nodeMap[l.target]) nodeMap[l.target]._degree++;
            return { source: l.source, target: l.target, type: l.type };
        });

        var highlightNodes = new Set();
        var highlightLinks = new Set();

        graph = ForceGraph()(container)
            .backgroundColor("#fbfbf9")
            .nodeId("id")
            .nodeLabel(function (node) {
                var tip = node.name;
                if (node.labels && node.labels.length) tip += "  (:" + node.labels.join(":") + ")";
                var props = node.properties || {};
                var keys = Object.keys(props);
                for (var i = 0; i < Math.min(keys.length, 6); i++) {
                    var v = props[keys[i]];
                    if (typeof v === "string" && v.length > 50) v = v.substring(0, 50) + "\u2026";
                    tip += "\n" + keys[i] + ": " + v;
                }
                return tip;
            })
            .linkSource("source")
            .linkTarget("target")
            .linkCurvature(0.15)
            .linkDirectionalArrowLength(5)
            .linkDirectionalArrowRelPos(0.85)
            .linkDirectionalArrowColor(function (link) {
                if (highlightNodes.size === 0) return "#94938c";
                return highlightLinks.has(link) ? "#5c5b54" : "#c8c7c2";
            })
            .linkColor(function (link) {
                if (highlightNodes.size === 0) return "#dad9d4";
                return highlightLinks.has(link) ? "#94938c" : "rgba(218,217,212,0.15)";
            })
            .linkWidth(function (link) {
                if (highlightNodes.size === 0) return 1;
                return highlightLinks.has(link) ? 1.5 : 0.3;
            })
            .linkLabel(function (link) { return link.type; })
            .nodeCanvasObject(function (node, ctx, globalScale) {
                var degree = node._degree || 0;
                var r = Math.max(4, Math.min(10, 4 + Math.sqrt(degree)));
                var lbl = (node.labels && node.labels[0]) || "Node";
                var isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
                var alpha = isHighlighted ? 1.0 : 0.25;

                ctx.save();
                ctx.globalAlpha = alpha;

                ctx.beginPath();
                ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
                ctx.fillStyle = labelColor(lbl);
                ctx.fill();

                var fontSize = Math.max(3, 10 / globalScale);
                ctx.font = fontSize + "px Inter, system-ui, sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = isHighlighted ? "#181612" : "#94938c";
                ctx.globalAlpha = isHighlighted ? 0.85 : 0.2;
                ctx.fillText(node.name, node.x, node.y + r + 2);

                ctx.restore();
            })
            .nodePointerAreaPaint(function (node, color, ctx) {
                var r = Math.max(4, Math.min(10, 4 + Math.sqrt(node._degree || 0)));
                ctx.beginPath();
                ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
            })
            .onNodeClick(function (node) {
                if (!node) return;
                highlightNodes.clear();
                highlightLinks.clear();
                highlightNodes.add(node.id);

                var allLinks = graph.graphData().links;
                for (var i = 0; i < allLinks.length; i++) {
                    var link = allLinks[i];
                    var srcId = typeof link.source === "object" ? link.source.id : link.source;
                    var tgtId = typeof link.target === "object" ? link.target.id : link.target;
                    if (srcId === node.id || tgtId === node.id) {
                        highlightNodes.add(srcId);
                        highlightNodes.add(tgtId);
                        highlightLinks.add(link);
                    }
                }
            })
            .onBackgroundClick(function () {
                highlightNodes.clear();
                highlightLinks.clear();
            })
            .onNodeHover(function (node) {
                var canvas = container.querySelector("canvas");
                if (canvas) canvas.style.cursor = node ? "pointer" : "default";
            })
            .onEngineStop(function () {
                if (graph) graph.zoomToFit(400, 30);
            })
            .autoPauseRedraw(false)
            .warmupTicks(100)
            .cooldownTicks(300)
            .width(w)
            .height(h)
            .graphData({ nodes: nodes, links: links });

        graph.d3Force("charge").strength(-200);
        graph.d3Force("link").distance(100);
    }

    function checkNeo4jStatus() {
        var statusEl = document.getElementById("neo4j-status");
        fetch("/api/neo4j/status")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.connected) {
                    statusEl.textContent = "neo4j connected";
                    statusEl.className = "neo4j-status connected";
                } else {
                    statusEl.textContent = "neo4j disconnected";
                    statusEl.className = "neo4j-status disconnected";
                }
            })
            .catch(function () {
                statusEl.textContent = "neo4j disconnected";
                statusEl.className = "neo4j-status disconnected";
            });
    }

    function saveHistory(cypher) {
        try {
            var history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
            history = history.filter(function (q) { return q !== cypher; });
            history.unshift(cypher);
            if (history.length > MAX_HISTORY) history = history.slice(0, MAX_HISTORY);
            localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        } catch (e) {
            // localStorage not available
        }
    }

    function showView() {
        document.getElementById("query-presets").style.display = "";
        checkNeo4jStatus();
        if (viewMode === "graph" && graphData) onResize();
    }

    function hideView() {
        document.getElementById("query-presets").style.display = "none";
    }

    return {
        init: init,
        showView: showView,
        hideView: hideView,
    };
})();
