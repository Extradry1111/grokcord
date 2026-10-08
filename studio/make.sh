#!/usr/bin/env bash
# make.sh <name> <w> <h> <fps> <secs> <gif_width>
set -euo pipefail
name=$1 w=$2 h=$3 fps=$4 secs=$5 gw=$6
node render.mjs "$name.html" "out/$name-frames" "$w" "$h" "$fps" "$secs"
ffmpeg -y -loglevel error -framerate "$fps" -i "out/$name-frames/f%05d.png" -c:v libx264 -pix_fmt yuv420p -crf 18 -preset slow -movflags +faststart "out/$name.mp4"
ffmpeg -y -loglevel error -framerate "$fps" -i "out/$name-frames/f%05d.png" \
  -vf "scale=$gw:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=200:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle" \
  -loop 0 "out/$name.gif"
ls -la "out/$name.gif" "out/$name.mp4" | awk '{print $5, $9}'
