// Stride sampler for chart time-series data. Returns the input
// untouched when shorter than `target`. The first and last points are
// always preserved; the rest are walked at a fixed interval.
//
// Presentational only — the input array is not mutated.
export default function downsample(arr, target = 120) {
  if (!Array.isArray(arr) || arr.length <= target) return arr;
  if (target < 2) return arr.slice(0, target);
  const stride = (arr.length - 1) / (target - 1);
  const out = [];
  for (let i = 0; i < target - 1; i++) {
    out.push(arr[Math.round(i * stride)]);
  }
  out.push(arr[arr.length - 1]);
  return out;
}
