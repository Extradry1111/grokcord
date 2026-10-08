# studio

Every grokcord visual is HTML + CSS, rendered frame by frame with Playwright and stitched with ffmpeg.

```bash
cd studio && npm i
# needs ffmpeg and a Chromium; point CHROMIUM_PATH at it if Playwright can't find one
./make.sh hero 1280 640 20 5 1000          # name, width, height, fps, seconds, gif width
./make.sh factcheck 960 600 20 8 800
./promo.sh                                  # 41s promo video → out/grokcord-promo.mp4
TRANSPARENT=1 node render.mjs logo.html out/logo.png 1024 1024 1 1 0
```

Scenes: `hero` · `factcheck` · `tldr` · `pulse` · `personas` · `intro` · `outro` · `logo`.
Timing lives in each page's `onSeek(ms)`, so every frame is deterministic.
