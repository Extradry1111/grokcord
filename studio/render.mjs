// Deterministic frame renderer: pauses every CSS/Web animation and seeks it to t for each frame.
// usage: node render.mjs <page.html> <outdir> <width> <height> <fps> <seconds> [stillAt]
import { chromium } from "playwright-core";
import { mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const [page_, out, w, h, fps, secs, still] = process.argv.slice(2);
const W = +w, H = +h, FPS = +fps, DUR = +secs;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: +(process.env.DPR || 1) });
await page.goto("file://" + resolve(page_));
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(300);

const seek = (ms) => page.evaluate((ms) => {
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = ms; }
  if (window.onSeek) window.onSeek(ms);
}, ms);

if (still !== undefined) {
  await seek(+still * 1000);
  await page.screenshot({ path: out, omitBackground: !!process.env.TRANSPARENT });
} else {
  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  const n = Math.round(DUR * FPS);
  for (let i = 0; i < n; i++) {
    await seek((i / FPS) * 1000);
    await page.screenshot({ path: `${out}/f${String(i).padStart(5, "0")}.png` });
  }
  console.log(`${n} frames → ${out}`);
}
await browser.close();
