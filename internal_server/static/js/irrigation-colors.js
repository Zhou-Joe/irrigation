/* Distribution-based map coloring; observations and tooltips stay unchanged. */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.IrrigationColors = factory();
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';
    function scale(values, manualMax) {
        const sorted = values.filter(v => typeof v === 'number' && Number.isFinite(v) && v > 0).sort((a,b) => a-b);
        const max = sorted[sorted.length-1] || 0;
        const manual = Number.isFinite(manualMax) && manualMax > 0;
        function quantile(p) {
            if (!sorted.length) return 0;
            const index = (sorted.length-1)*p, lo = Math.floor(index), hi = Math.ceil(index);
            return sorted[lo] + (sorted[hi]-sorted[lo])*(index-lo);
        }
        function position(value) {
            if (!Number.isFinite(value) || value <= 0) return 0;
            if (manual) return Math.min(value/manualMax,1);
            if (!sorted.length) return 0;
            if (sorted[0] === max) return .5;
            let lo=0, hi=sorted.length;
            while (lo<hi) { const mid=(lo+hi)>>>1; if (sorted[mid]<value) lo=mid+1; else hi=mid; }
            const first=lo; hi=sorted.length;
            while (lo<hi) { const mid=(lo+hi)>>>1; if (sorted[mid]<=value) lo=mid+1; else hi=mid; }
            // Midranks give equal observations exactly the same color. Positive
            // values start above the zero tint; extreme magnitudes cannot squash
            // the rest of the distribution into the first green interval.
            return Math.max(0,Math.min(1,.12+.88*((first+lo-1)/2)/(sorted.length-1)));
        }
        return {kind:manual?'manual':'quantile',max,low:quantile(0),median:quantile(.5),position};
    }
    return {scale};
});
