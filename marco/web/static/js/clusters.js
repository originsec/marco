/**
 * Module clustering visualization.
 *
 * Renders module clusters as a force-directed graph with
 * cluster-based coloring and grouping.
 *
 * Public API: init(), load(explorationData), resize(), destroy().
 */
var Clusters = (function () {
    "use strict";

    var graph = null;
    var container = null;
    var statusEl = null;
    var clusterData = null;
    var currentNodes = [];
    var currentLinks = [];
    var selectedNode = null;
    var highlightNodes = new Set();
    var highlightLinks = new Set();
    var needsInitialZoom = false;

    // Tableau 10 — well-separated, colorblind-accessible
    var CLUSTER_COLORS = [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
        "#59a14f", "#edc948", "#b07aa1", "#9c755f",
    ];

    function clusterColor(clusterId) {
        if (clusterId == null || clusterId < 0) return "#94938c";
        return CLUSTER_COLORS[clusterId % CLUSTER_COLORS.length];
    }

    function nodeRadius(d) {
        var degree = (d._imports || 0) + (d._importedBy || 0);
        return Math.max(3, Math.min(8, 3 + Math.sqrt(degree)));
    }

    /** Pull same-cluster nodes toward their centroid. */
    function makeClusterForce(strength) {
        var nodes;
        function force(alpha) {
            // Compute centroids per cluster
            var cx = {}, cy = {}, count = {};
            for (var i = 0; i < nodes.length; i++) {
                var c = nodes[i].cluster;
                if (c == null) continue;
                if (!count[c]) { cx[c] = 0; cy[c] = 0; count[c] = 0; }
                cx[c] += nodes[i].x;
                cy[c] += nodes[i].y;
                count[c]++;
            }
            for (var k in count) {
                cx[k] /= count[k];
                cy[k] /= count[k];
            }
            // Pull toward centroid
            for (var j = 0; j < nodes.length; j++) {
                var cl = nodes[j].cluster;
                if (cl == null || !count[cl]) continue;
                nodes[j].vx += (cx[cl] - nodes[j].x) * strength * alpha;
                nodes[j].vy += (cy[cl] - nodes[j].y) * strength * alpha;
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

    function init() {
        container = document.getElementById("cluster-graph-container");
        statusEl = document.getElementById("cluster-status");
    }

    function showStatus(msg) {
        if (!statusEl) return;
        statusEl.style.display = "";
        statusEl.textContent = msg;
    }

    function hideStatus() {
        if (!statusEl) return;
        statusEl.style.display = "none";
        statusEl.textContent = "";
    }

    var _loading = false;

    function load(explorationData) {
        if (!container) return;

        // Already loaded or in-flight — just resize
        if (clusterData) { resize(); return; }
        if (_loading) return;
        _loading = true;

        // Show computing state
        showStatus("computing clusters\u2026");

        fetch("/api/clusters/compute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                _loading = false;
                if (data.error) {
                    showStatus(data.error);
                    return;
                }
                hideStatus();
                clusterData = data;
                renderGraph(explorationData, data);
                showClusterList();
            })
            .catch(function (err) {
                _loading = false;
                showStatus("failed to compute clusters");
                console.error("Cluster compute error:", err);
            });
    }

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
                if (highlightNodes.size === 0) return "#dad9d4";
                return highlightLinks.has(link) ? "#94938c" : "#dad9d4";
            })
            .linkColor(function (link) {
                if (highlightNodes.size === 0) return "#e6e5e0";
                return highlightLinks.has(link) ? "#b8bbc6" : "rgba(230,229,224,0.12)";
            })
            .linkWidth(function (link) {
                if (highlightNodes.size === 0) return 0.4;
                return highlightLinks.has(link) ? 1.2 : 0.2;
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

        graph.d3Force("charge").strength(-300);
        graph.d3Force("link").distance(80);
        graph.d3Force("collide", makeCollideForce(function (d) {
            return nodeRadius(d) + 6;
        }));
        graph.d3Force("cluster", makeClusterForce(0.08));

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

        // Cluster color ring
        ctx.beginPath();
        ctx.arc(x, y, r + 1.5, 0, 2 * Math.PI);
        ctx.strokeStyle = clusterColor(node.cluster);
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Node fill — cluster color
        ctx.beginPath();
        ctx.arc(x, y, r, 0, 2 * Math.PI);
        ctx.fillStyle = clusterColor(node.cluster);
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

    function renderGraph(explorationData, clData) {
        if (!container) return;

        // Destroy previous instance if any
        if (graph) {
            graph._destructor();
            graph = null;
        }

        createGraph();
        if (!graph) return;

        var gd = buildGraphData(explorationData, clData);
        currentNodes = gd.nodes;
        currentLinks = gd.links;

        needsInitialZoom = true;
        graph.graphData({ nodes: currentNodes, links: currentLinks });
    }

    function buildGraphData(explorationData, clData) {
        var nodes = [];
        var links = [];
        var nodeMap = {};

        if (!explorationData || !explorationData.modules) {
            return { nodes: nodes, links: links };
        }

        var modules = explorationData.modules;
        var edges = explorationData.edges || [];
        var assignments = clData ? clData.assignments || {} : {};

        // Count imports and imported-by
        var importCounts = {};
        var importedByCounts = {};
        for (var e = 0; e < edges.length; e++) {
            var src = edges[e].source.toLowerCase ? edges[e].source.toLowerCase() : edges[e].source;
            var tgt = edges[e].target.toLowerCase ? edges[e].target.toLowerCase() : edges[e].target;
            importCounts[src] = (importCounts[src] || 0) + 1;
            importedByCounts[tgt] = (importedByCounts[tgt] || 0) + 1;
        }

        for (var i = 0; i < modules.length; i++) {
            var m = modules[i];
            var id = m.name.toLowerCase();
            // Look up cluster assignment — try with and without file extension
            var cluster = assignments[m.name];
            if (cluster == null) cluster = assignments[m.name.toLowerCase()];
            var stem = m.name.replace(/\.(dll|sys|exe|drv|cpl|ocx)$/i, "");
            if (cluster == null) cluster = assignments[stem];
            if (cluster == null) cluster = assignments[stem.toLowerCase()];
            if (cluster == null) cluster = -1;

            var node = {
                id: id,
                name: m.name,
                cluster: cluster,
                depth: m.depth || 0,
                status: m.status || "queued",
                _imports: importCounts[id] || 0,
                _importedBy: importedByCounts[id] || 0,
            };
            nodes.push(node);
            nodeMap[id] = true;
        }

        for (var j = 0; j < edges.length; j++) {
            var s = edges[j].source.toLowerCase ? edges[j].source.toLowerCase() : edges[j].source;
            var t = edges[j].target.toLowerCase ? edges[j].target.toLowerCase() : edges[j].target;
            if (nodeMap[s] && nodeMap[t]) {
                links.push({ source: s, target: t });
            }
        }

        return { nodes: nodes, links: links };
    }

    function onNodeClick(node) {
        if (!node) return;

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
        showClusterSidenote(node);
    }

    function onBackgroundClick() {
        highlightNodes.clear();
        highlightLinks.clear();
        selectedNode = null;
    }

    function onNodeHover(node) {
        var canvas = container && container.querySelector("canvas");
        if (canvas) canvas.style.cursor = node ? "pointer" : "default";
    }

    function showClusterList() {
        if (!clusterData || !clusterData.clusters) return;

        var content = document.getElementById("sidenote-content");
        if (!content) return;

        var clusters = clusterData.clusters;
        var html = '<div class="sidenote">';
        html += '<h3>clusters</h3>';
        var noiseCount = (clusterData.noise_modules || []).length;
        html += '<p style="color:#94938c">' + clusterData.n_clusters + ' clusters from ' + clusterData.n_modules + ' modules';
        if (noiseCount > 0) html += ' (' + noiseCount + ' unclustered)';
        html += '</p>';
        if (!clusterData.labeled) {
            html += '<p style="color:#94938c;font-size:0.78rem;font-style:italic">'
                + 'Set ANTHROPIC_API_KEY for cluster summaries</p>';
        }

        for (var i = 0; i < clusters.length; i++) {
            var c = clusters[i];
            html += '<div class="cluster-item" style="margin-top:0.5rem">';
            html += '<p><span class="cluster-swatch" style="background:' + clusterColor(c.id) + '"></span> ';
            var clusterTitle = c.label || ('Cluster ' + c.id);
            html += '<strong>' + esc(clusterTitle) + '</strong> <span style="color:#94938c">(' + c.modules.length + ')</span></p>';

            html += '<div class="dep-list">';
            for (var j = 0; j < c.modules.length; j++) {
                html += '<span>' + esc(c.modules[j]) + '</span>';
            }
            html += '</div>';
            html += '</div>';
        }

        // Show noise/unclustered modules
        var noise = clusterData.noise_modules || [];
        if (noise.length > 0) {
            html += '<div style="margin-top:0.75rem">';
            html += '<p><span class="cluster-swatch" style="background:#94938c"></span> ';
            html += '<strong>Unclustered</strong> <span style="color:#94938c">(' + noise.length + ')</span></p>';
            html += '<div class="dep-list">';
            for (var n = 0; n < noise.length; n++) {
                html += '<span class="not-analyzed">' + esc(noise[n]) + '</span>';
            }
            html += '</div></div>';
        }

        html += '</div>';
        content.innerHTML = html;
    }

    function showClusterSidenote(node) {
        if (!clusterData) return;

        var content = document.getElementById("sidenote-content");
        if (!content) return;

        var html = '<div class="sidenote">';
        html += '<h3>' + esc(node.name) + '</h3>';

        if (node.cluster >= 0) {
            var cluster = null;
            for (var i = 0; i < clusterData.clusters.length; i++) {
                if (clusterData.clusters[i].id === node.cluster) {
                    cluster = clusterData.clusters[i];
                    break;
                }
            }

            if (cluster) {
                var detailTitle = cluster.label || ('Cluster ' + node.cluster);
                html += '<p><span class="cluster-swatch" style="background:' + clusterColor(node.cluster) + '"></span> ';
                html += esc(detailTitle) + '</p>';
                if (cluster.description) {
                    html += '<p style="color:#5c5b54;font-size:0.8rem">' + esc(cluster.description) + '</p>';
                }
                html += '<table class="detail-table">';
                html += '<tr><td>modules</td><td class="num">' + cluster.modules.length + '</td></tr>';
                html += '</table>';

                // Module list
                html += '<p style="margin-top:0.5rem;font-weight:600">members</p>';
                html += '<div class="dep-list">';
                var nodeStem = node.name.replace(/\.(dll|sys|exe|drv|cpl|ocx)$/i, "").toLowerCase();
                for (var j = 0; j < cluster.modules.length; j++) {
                    var isCurrent = cluster.modules[j].toLowerCase() === nodeStem;
                    html += '<span' + (isCurrent ? ' style="font-weight:600"' : '') + '>';
                    html += esc(cluster.modules[j]) + '</span>';
                }
                html += '</div>';

                // Characteristic functions
                var funcs = cluster.characteristic_functions || [];
                if (funcs.length > 0) {
                    html += '<p style="margin-top:0.5rem;font-weight:600">characteristic functions</p>';
                    html += '<div class="cluster-functions">';
                    for (var k = 0; k < funcs.length; k++) {
                        html += '<span>' + esc(funcs[k]) + '</span>';
                    }
                    html += '</div>';
                }
            }
        } else {
            html += '<p class="empty-state">Not assigned to any cluster</p>';
        }

        html += '</div>';
        content.innerHTML = html;
    }

    function esc(s) {
        if (typeof Table !== "undefined" && Table.esc) return Table.esc(s);
        var el = document.createElement("span");
        el.textContent = s;
        return el.innerHTML;
    }

    function resize() {
        if (!container || !graph) return;
        var w = container.clientWidth;
        var h = container.clientHeight;
        if (w === 0 || h === 0) return;
        graph.width(w).height(h);
    }

    function destroy() {
        if (graph) {
            graph._destructor();
            graph = null;
        }
        currentNodes = [];
        currentLinks = [];
        clusterData = null;
        _loading = false;
        selectedNode = null;
        highlightNodes.clear();
        highlightLinks.clear();
    }

    return {
        init: init,
        load: load,
        resize: resize,
        destroy: destroy,
    };
})();
