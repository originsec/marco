/**
 * Shared Tufte-style table renderer.
 * No vertical rules, thin horizontal rules, right-aligned numbers.
 */
var Table = (function () {
    "use strict";

    /**
     * Render a data table.
     *
     * @param {string[]} columns - Column header labels
     * @param {Array<Array>} rows - Row data (array of arrays)
     * @param {Object} [options] - Rendering options
     * @param {boolean[]} [options.numeric] - Which columns are numeric (right-aligned)
     * @returns {string} HTML table string
     */
    function render(columns, rows, options) {
        options = options || {};
        var numeric = options.numeric || [];

        var html = '<table><thead><tr>';
        for (var c = 0; c < columns.length; c++) {
            var cls = numeric[c] ? ' class="num"' : "";
            html += "<th" + cls + ">" + esc(columns[c]) + "</th>";
        }
        html += "</tr></thead><tbody>";

        for (var r = 0; r < rows.length; r++) {
            html += "<tr>";
            for (var j = 0; j < columns.length; j++) {
                var val = rows[r][j];
                var cls2 = numeric[j] ? ' class="num"' : "";
                html += "<td" + cls2 + ">" + formatValue(val) + "</td>";
            }
            html += "</tr>";
        }

        html += "</tbody></table>";
        return html;
    }

    function formatValue(val) {
        if (val === null || val === undefined) return "";
        if (typeof val === "number") return formatNumber(val);
        if (typeof val === "object") return esc(JSON.stringify(val));
        return esc(String(val));
    }

    function formatNumber(n) {
        if (Number.isInteger(n)) return n.toLocaleString();
        return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    function esc(s) {
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(s));
        return div.innerHTML;
    }

    return { render: render, formatNumber: formatNumber, esc: esc };
})();
