/**
 * Main application controller.
 * Handles WebSocket connection, hash routing, and view switching.
 */
(function () {
    "use strict";

    var ws = null;
    var reconnectTimer = null;
    var currentView = "analysis";

    function init() {
        Analysis.init();
        Exploration.init();
        DepGraph.init();
        Clusters.init();
        Query.init();

        setupToggle();
        setupRouting();
        connectWebSocket();

        // 1-second tick for live elapsed timers
        setInterval(function () {
            Analysis.tick();
        }, 1000);
    }

    function setupToggle() {
        var toggle = document.getElementById("explore-view-toggle");
        if (!toggle) return;
        toggle.addEventListener("click", function (e) {
            var btn = e.target.closest(".toggle-btn");
            if (!btn) return;
            var mode = btn.getAttribute("data-mode");
            if (mode) Exploration.setViewMode(mode);
        });
    }

    function setupRouting() {
        window.addEventListener("hashchange", onHashChange);
        onHashChange();
    }

    function onHashChange() {
        var hash = window.location.hash.replace("#", "") || "analysis";
        switchView(hash);
    }

    function switchView(view) {
        if (view !== "analysis" && view !== "explore" && view !== "query") {
            view = "analysis";
        }

        currentView = view;

        // Update nav
        var links = document.querySelectorAll("nav a");
        for (var i = 0; i < links.length; i++) {
            var linkView = links[i].getAttribute("data-view");
            if (linkView === view) {
                links[i].classList.add("active");
            } else {
                links[i].classList.remove("active");
            }
        }

        // Show/hide views
        var views = document.querySelectorAll(".view");
        for (var j = 0; j < views.length; j++) {
            var viewId = views[j].id.replace("view-", "");
            if (viewId === view) {
                views[j].classList.add("active");
            } else {
                views[j].classList.remove("active");
            }
        }

        // View-specific actions
        if (view === "explore") {
            Exploration.load();
        }

        if (view === "query") {
            Query.showView();
        } else {
            Query.hideView();
        }

        // Show/hide query presets in sidenote
        var placeholder = document.getElementById("sidenote-placeholder");
        if (view === "query") {
            if (placeholder) placeholder.style.display = "none";
        } else {
            if (placeholder) placeholder.style.display = "";
        }
    }

    function connectWebSocket() {
        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = protocol + "//" + window.location.host + "/ws";

        ws = new WebSocket(url);

        ws.onopen = function () {
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);
                handleMessage(data);
            } catch (e) {
                console.error("Failed to parse WebSocket message:", e);
            }
        };

        ws.onclose = function () {
            scheduleReconnect();
        };

        ws.onerror = function () {
            // onclose will fire after this
        };
    }

    function scheduleReconnect() {
        if (!reconnectTimer) {
            reconnectTimer = setTimeout(function () {
                reconnectTimer = null;
                connectWebSocket();
            }, 2000);
        }
    }

    function handleMessage(data) {
        if (data.type === "state_snapshot") {
            Analysis.updateState(data);
            Exploration.updateFromState(data);
            if (currentView === "explore") {
                Exploration.renderCurrentView();
            }
        } else {
            // All events route through Analysis (handles phase events too)
            Analysis.handleEvent(data);

            if (data.type === "binary_completed" || data.type === "analysis_complete") {
                if (currentView === "explore") {
                    Exploration.load();
                }
            }
        }
    }

    // Initialize on DOM ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
