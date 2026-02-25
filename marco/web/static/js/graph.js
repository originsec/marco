/**
 * 2D force-directed graph for the explore view.
 *
 * Renders modules as nodes and import relationships as directed edges
 * using force-graph (HTML5 Canvas). Nodes encode depth via color,
 * degree centrality via size, and status via border rings.
 *
 * Public API: init(), render(), update(), resize(), destroy().
 */
var DepGraph = (function () {
    "use strict";

    var graph = null;
    var container = null;
    var currentNodes = [];
    var currentLinks = [];
    var pendingData = null;
    var selectedNode = null;
    var highlightNodes = new Set();
    var highlightLinks = new Set();
    var needsInitialZoom = false;

    // Depth palette: dark (seeds) -> light (deep transitive)
    var DEPTH_COLORS = [
        "#2b2d42",  // depth 0 — seeds
        "#5e6472",  // depth 1
        "#8d91a0",  // depth 2
        "#b8bbc6",  // depth 3+
    ];

    // Simple custom forces — avoids needing standalone d3-force CDN.
    // force-graph bundles its own d3-force internally for charge/link/center.

    /** Pull each node's Y toward (depth * spacing). */
    function makeDepthYForce(spacing, strength) {
        var nodes;
        function force(alpha) {
            for (var i = 0; i < nodes.length; i++) {
                var target = (nodes[i].depth || 0) * spacing;
                nodes[i].vy += (target - nodes[i].y) * strength * alpha;
            }
        }
        force.initialize = function (_nodes) { nodes = _nodes; };
        return force;
    }

    /** O(n^2) collision — fine for <500 nodes. */
    function makeCollideForce(radiusFn) {
        var nodes;
        function force() {
            for (var i = 0; i < nodes.length; i++) {
                var ri = radiusFn(nodes[i]);
                for (var j = i + 1; j < nodes.length; j++) {
                    var rj = radiusFn(nodes[j]);
                    var dx = nodes[j].x - nodes[i].x;
                    var dy = nodes[j].y - nodes[i].y;
                    var dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    var minDist = ri + rj;
                    if (dist < minDist) {
                        var push = (minDist - dist) / dist * 0.5;
                        nodes[i].x -= dx * push;
                        nodes[i].y -= dy * push;
                        nodes[j].x += dx * push;
                        nodes[j].y += dy * push;
                    }
                }
            }
        }
        force.initialize = function (_nodes) { nodes = _nodes; };
        return force;
    }

    var STATUS_RING_COLORS = {
        analyzing: "#c49a3c",
        queued: "#dad9d4",
        error: "#a86262",
    };

    function depthColor(d) {
        var idx = Math.min(d.depth || 0, DEPTH_COLORS.length - 1);
        return DEPTH_COLORS[idx];
    }

    function nodeRadius(d) {
        var degree = (d._imports || 0) + (d._importedBy || 0);
        return Math.max(3, Math.min(8, 3 + Math.sqrt(degree)));
    }

    function hasSpecialEdges(d) {
        if (!d.edge_kind_counts) return false;
        var ekc = d.edge_kind_counts;
        for (var kind in ekc) {
            if (ekc.hasOwnProperty(kind)) {
                var k = kind.toUpperCase();
                if (k !== "CALLS" && k !== "IMPORTS" && ekc[kind] > 0) return true;
            }
        }
        return false;
    }

    /** Create the force-graph instance. Only call when container is visible. */
    function createGraph() {
        if (graph || !container) return false;
        var w = container.clientWidth;
        var h = container.clientHeight;
        if (w === 0 || h === 0) return false;

        graph = ForceGraph()(container)
            .backgroundColor("#fbfbf9")
            .nodeId("id")
            .nodeLabel("")
            .linkSource("source")
            .linkTarget("target")
            .linkCurvature(0.15)
            .linkDirectionalArrowLength(5)
            .linkDirectionalArrowRelPos(0.85)
            .linkDirectionalArrowColor(function (link) {
                if (highlightNodes.size === 0) return "#c8c7c2";
                return highlightLinks.has(link) ? "#5c5b54" : "#c8c7c2";
            })
            .linkColor(function (link) {
                if (highlightNodes.size === 0) return "#e6e5e0";
                return highlightLinks.has(link) ? "#94938c" : "rgba(230,229,224,0.15)";
            })
            .linkWidth(function (link) {
                if (highlightNodes.size === 0) return 0.5;
                return highlightLinks.has(link) ? 1.5 : 0.3;
            })
            .nodeCanvasObject(drawNode)
            .nodePointerAreaPaint(nodePointerArea)
            .onNodeClick(onNodeClick)
            .onBackgroundClick(onBackgroundClick)
            .onNodeHover(onNodeHover)
            .onEngineStop(onEngineStop)
            .autoPauseRedraw(false)
            .warmupTicks(100)
            .cooldownTicks(500)
            .width(w)
            .height(h);

        // --- Force configuration ---
        graph.d3Force("charge").strength(-300);
        graph.d3Force("link").distance(80);
        graph.d3Force("collide", makeCollideForce(function (d) {
            return nodeRadius(d) + 6;
        }));
        graph.d3Force("depthY", makeDepthYForce(100, 0.1));

        // Replay any data that arrived before the graph was created
        if (pendingData) {
            var d = pendingData;
            pendingData = null;
            render(d);
        }

        return true;
    }

    function onEngineStop() {
        if (needsInitialZoom && graph) {
            needsInitialZoom = false;
            graph.zoomToFit(400, 30);
        }
    }

    function drawNode(node, ctx, globalScale) {
        var r = nodeRadius(node);
        var x = node.x;
        var y = node.y;
        var isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
        var alpha = isHighlighted ? 1.0 : 0.3;

        ctx.save();
        ctx.globalAlpha = alpha;

        // Status ring (during analysis) or special-edges ring (after)
        var ringColor = null;
        if (node.status !== "completed") {
            ringColor = STATUS_RING_COLORS[node.status] || null;
        } else if (hasSpecialEdges(node)) {
            ringColor = "#c49a3c";
        }

        if (ringColor) {
            ctx.beginPath();
            ctx.arc(x, y, r + 1.5, 0, 2 * Math.PI);
            ctx.strokeStyle = ringColor;
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }

        // Node fill
        ctx.beginPath();
        ctx.arc(x, y, r, 0, 2 * Math.PI);
        ctx.fillStyle = depthColor(node);
        ctx.fill();

        // Label
        var degree = (node._imports || 0) + (node._importedBy || 0);
        var showLabel = degree >= 5 || globalScale > 0.7;
        if (showLabel) {
            var fontSize = Math.max(3, 10 / globalScale);
            ctx.font = fontSize + "px Inter, system-ui, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = isHighlighted ? "#181612" : "#94938c";
            ctx.globalAlpha = isHighlighted ? 0.9 : 0.25;
            ctx.fillText(node.name, x, y + r + 2);
        }

        ctx.restore();
    }

    function nodePointerArea(node, color, ctx) {
        var r = nodeRadius(node);
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
    }

    function init() {
        container = document.getElementById("explore-graph-container");
        if (!container) return;
        window.addEventListener("resize", resize);
    }

    function resize() {
        if (!container) return;
        var w = container.clientWidth;
        var h = container.clientHeight;
        if (w === 0 || h === 0) return;

        if (!graph) {
            createGraph();
            return;
        }

        graph.width(w).height(h);
    }

    function buildGraphData(data) {
        if (!data || !data.modules || data.modules.length === 0) {
            return { nodes: [], links: [] };
        }

        var nodeMap = {};

        // Count imports and imported-by from edges
        var importCounts = {};
        var importedByCounts = {};
        var edges = data.edges || [];
        for (var e = 0; e < edges.length; e++) {
            var src = edges[e].source.toLowerCase ? edges[e].source.toLowerCase() : edges[e].source;
            var tgt = edges[e].target.toLowerCase ? edges[e].target.toLowerCase() : edges[e].target;
            importCounts[src] = (importCounts[src] || 0) + 1;
            importedByCounts[tgt] = (importedByCounts[tgt] || 0) + 1;
        }

        var nodes = data.modules.map(function (m) {
            var id = m.name.toLowerCase();
            var node = {
                id: id,
                name: m.name,
                status: m.status || "queued",
                node_count: m.node_count || 0,
                depth: m.depth || 0,
                edge_kind_counts: m.edge_kind_counts || {},
                _imports: importCounts[id] || 0,
                _importedBy: importedByCounts[id] || 0,
            };
            nodeMap[node.id] = true;
            return node;
        });

        var links = [];
        for (var i = 0; i < edges.length; i++) {
            var s = edges[i].source.toLowerCase ? edges[i].source.toLowerCase() : edges[i].source;
            var t = edges[i].target.toLowerCase ? edges[i].target.toLowerCase() : edges[i].target;
            if (nodeMap[s] && nodeMap[t]) {
                links.push({ source: s, target: t });
            }
        }

        return { nodes: nodes, links: links };
    }

    function render(data) {
        if (!graph) {
            pendingData = data;
            return;
        }

        clearHighlight();
        var gd = buildGraphData(data);
        currentNodes = gd.nodes;
        currentLinks = gd.links;

        needsInitialZoom = true;
        graph.graphData({ nodes: currentNodes, links: currentLinks });
    }

    function update(data) {
        if (!graph) {
            pendingData = data;
            return;
        }

        if (currentNodes.length === 0) {
            render(data);
            return;
        }

        // Preserve existing node positions
        var oldMap = {};
        var existing = graph.graphData().nodes;
        for (var i = 0; i < existing.length; i++) {
            var n = existing[i];
            oldMap[n.id] = { x: n.x, y: n.y, vx: n.vx, vy: n.vy };
        }

        var gd = buildGraphData(data);
        currentNodes = gd.nodes;
        currentLinks = gd.links;

        for (var j = 0; j < currentNodes.length; j++) {
            var old = oldMap[currentNodes[j].id];
            if (old) {
                currentNodes[j].x = old.x;
                currentNodes[j].y = old.y;
                currentNodes[j].vx = old.vx;
                currentNodes[j].vy = old.vy;
            }
        }

        graph.graphData({ nodes: currentNodes, links: currentLinks });
        graph.d3ReheatSimulation();
    }

    function onNodeClick(node) {
        if (!node) return;

        // Focus + context: highlight node and 1-hop neighbors
        highlightNodes.clear();
        highlightLinks.clear();

        highlightNodes.add(node.id);

        var links = graph.graphData().links;
        for (var i = 0; i < links.length; i++) {
            var link = links[i];
            var srcId = typeof link.source === "object" ? link.source.id : link.source;
            var tgtId = typeof link.target === "object" ? link.target.id : link.target;
            if (srcId === node.id || tgtId === node.id) {
                highlightNodes.add(srcId);
                highlightNodes.add(tgtId);
                highlightLinks.add(link);
            }
        }

        selectedNode = node.id;

        if (typeof Exploration !== "undefined" && Exploration.showSidenote) {
            Exploration.showSidenote(node.name);
        }
    }

    function onBackgroundClick() {
        clearHighlight();
    }

    function clearHighlight() {
        highlightNodes.clear();
        highlightLinks.clear();
        selectedNode = null;
    }

    function onNodeHover(node) {
        var canvas = container && container.querySelector("canvas");
        if (canvas) canvas.style.cursor = node ? "pointer" : "default";
    }

    function destroy() {
        window.removeEventListener("resize", resize);
        if (graph) {
            graph._destructor();
            graph = null;
        }
        currentNodes = [];
        currentLinks = [];
        pendingData = null;
        selectedNode = null;
        highlightNodes.clear();
        highlightLinks.clear();
    }

    return {
        init: init,
        render: render,
        update: update,
        resize: resize,
        destroy: destroy,
    };
})();
