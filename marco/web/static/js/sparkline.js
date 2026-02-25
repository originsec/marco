/**
 * Inline SVG sparkline generator.
 * Word-sized sparklines following Tufte's small-multiples principle.
 */
var Sparkline = (function () {
    "use strict";

    /**
     * Generate an inline SVG sparkline from an array of timestamps.
     * Groups timestamps into buckets and plots throughput.
     *
     * @param {number[]} timestamps - Unix timestamps of completion events
     * @param {number} [width=60] - SVG width in pixels
     * @param {number} [height=14] - SVG height in pixels
     * @param {number} [buckets=8] - Number of time buckets
     * @returns {string} SVG markup string
     */
    function fromTimestamps(timestamps, width, height, buckets) {
        width = width || 60;
        height = height || 14;
        buckets = buckets || 8;

        if (!timestamps || timestamps.length < 2) {
            return "";
        }

        var min = timestamps[0];
        var max = timestamps[timestamps.length - 1];
        var range = max - min;

        if (range <= 0) return "";

        var counts = new Array(buckets).fill(0);
        for (var i = 0; i < timestamps.length; i++) {
            var idx = Math.min(Math.floor(((timestamps[i] - min) / range) * buckets), buckets - 1);
            counts[idx]++;
        }

        var maxCount = Math.max.apply(null, counts);
        if (maxCount === 0) return "";

        var points = [];
        for (var b = 0; b < buckets; b++) {
            var x = (b / (buckets - 1)) * width;
            var y = height - (counts[b] / maxCount) * (height - 2) - 1;
            points.push(x.toFixed(1) + "," + y.toFixed(1));
        }

        return '<svg class="sparkline" width="' + width + '" height="' + height +
            '" viewBox="0 0 ' + width + " " + height + '">' +
            '<polyline points="' + points.join(" ") + '"/></svg>';
    }

    return { fromTimestamps: fromTimestamps };
})();
