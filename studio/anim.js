// Tiny timeline helpers. Each scene defines scene(t) (t in seconds); render.mjs calls window.onSeek(ms).
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const seg = (t, a, b) => clamp((t - a) / (b - a));
const easeOut = (x) => 1 - Math.pow(1 - x, 3);
const easeInOut = (x) => (x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const back = (x) => { const c = 1.7; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

// fade+rise an element in at [a, a+d]
function enter(el, t, a, d = .35, dy = 14) {
  const p = easeOut(seg(t, a, a + d));
  el.style.opacity = p;
  el.style.transform = `translateY(${(1 - p) * dy}px)`;
}
// typewriter: reveal el.dataset.full over [a, b]
function type(el, t, a, b) {
  const full = el.dataset.full ?? (el.dataset.full = el.textContent);
  const n = Math.round(full.length * seg(t, a, b));
  el.textContent = full.slice(0, n);
  el.classList.toggle("caret", t >= a && t < b + .4);
}
// global fade for clean loops
function loopFade(t, dur, f = .35) {
  const o = Math.min(seg(t, 0, f), 1 - seg(t, dur - f, dur));
  document.querySelector(".stage").style.opacity = o;
}
window.addEventListener("load", () => window.onSeek && window.onSeek(0));
