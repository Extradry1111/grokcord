#!/usr/bin/env bash
set -euo pipefail
mkdir -p out/promo
seg() { # name w h secs dpr
  DPR=$5 node render.mjs "$1.html" "out/promo/$1" "$2" "$3" 30 "$4"
  ffmpeg -y -loglevel error -framerate 30 -i "out/promo/$1/f%05d.png" \
    -vf "scale=-2:720:flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x07070b,format=yuv420p" \
    -c:v libx264 -crf 17 -preset slow -r 30 "out/promo/$1.mp4"
}
seg intro 1280 720 5 1
seg factcheck 1067 600 8 1.2
seg tldr 1067 600 8 1.2
seg pulse 1067 600 8 1.2
seg personas 1067 600 8.4 1.2
seg outro 1280 720 4 1
printf "file '%s.mp4'\n" intro factcheck tldr pulse personas outro > out/promo/list.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i out/promo/list.txt -c copy -movflags +faststart out/grokcord-promo.mp4
ffprobe -v error -show_entries format=duration,size -of default=nw=1 out/grokcord-promo.mp4
