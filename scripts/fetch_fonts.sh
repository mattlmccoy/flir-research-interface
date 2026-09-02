#!/usr/bin/env bash
# Downloads IBM Plex Sans/Mono woff2 (latin subset) from Google Fonts into frontend/public/fonts.
# Run once; the files are committed so builds and offline mode need no network.
set -euo pipefail
OUT="$(cd "$(dirname "$0")/.." && pwd)/frontend/public/fonts"
mkdir -p "$OUT"
# NOTE: the Safari UA below is what Google's docs commonly suggest, but as of this
# writing it makes the CSS2 API return legacy .woff URLs instead of .woff2. A recent
# Chrome UA reliably gets .woff2. Kept configurable in case that flips again.
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
fetch() { # family weight outfile
  css=$(curl -sL -A "$UA" "https://fonts.googleapis.com/css2?family=$1:wght@$2&display=swap")
  # The CSS2 response contains one @font-face block per unicode subset (cyrillic-ext,
  # cyrillic, greek, vietnamese, latin-ext, latin, ...). We want ONLY the "latin"
  # block's font file, not just the first url in the response (which is cyrillic-ext).
  url=$(printf '%s' "$css" | awk '
    /^\/\*/ { sub(/^\/\* */,""); sub(/ *\*\/$/,""); subset=$0; next }
    { buf = buf "\n" $0 }
    /^}/ { if (subset=="latin") { print buf; exit } buf="" }
  ' | grep -o 'https://fonts.gstatic.com/[^)]*\.woff2' | head -1)
  [ -n "$url" ] || { echo "no latin woff2 url for $1 $2" >&2; exit 1; }
  curl -sL "$url" -o "$OUT/$3"; echo "$3 <- $url"
}
fetch "IBM+Plex+Sans" 400 IBMPlexSans-400.woff2
fetch "IBM+Plex+Sans" 500 IBMPlexSans-500.woff2
fetch "IBM+Plex+Sans" 600 IBMPlexSans-600.woff2
fetch "IBM+Plex+Mono" 400 IBMPlexMono-400.woff2
fetch "IBM+Plex+Mono" 500 IBMPlexMono-500.woff2
fetch "IBM+Plex+Mono" 600 IBMPlexMono-600.woff2
ls -la "$OUT"
