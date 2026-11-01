#!/usr/bin/env bash
# Fetch pinned aarch64 end-4 tools into build/; the installed release copies them.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
root=$(readlink -f "$here/..")
if [ "${1:-}" != --inner ]; then
  . "$root/scripts/_env.sh"
  if [ "$FRAME_LOCAL" = 0 ]; then
    "$root/scripts/sync.sh"
    exec "$root/scripts/frame.sh" 'session/build-end4-tools.sh --inner'
  fi
  if [ "${FRAME_IN_BOX:-0}" = 1 ]; then
    exec "$0" --inner
  fi
  exec "$root/scripts/in-box" "$0" --inner
fi
[ "$(uname -m)" = aarch64 ] || { echo 'frametop: end-4 tools require aarch64' >&2; exit 1; }
version=1.27.0
sha=341f5cbf24699fa0b27ec88965ad25f862ea09e15d35a543fd6ffdff1d2aa00d
out=$root/build/end4
mkdir -p "$out/bin" "$out/downloads"
archive=$out/downloads/starship-$version.tar.gz
if [ ! -f "$archive" ] || ! printf '%s  %s\n' "$sha" "$archive" | sha256sum -c --status; then
  curl -fL "https://github.com/starship/starship/releases/download/v$version/starship-aarch64-unknown-linux-musl.tar.gz" -o "$archive.part"
  printf '%s  %s\n' "$sha" "$archive.part" | sha256sum -c
  mv "$archive.part" "$archive"
fi
printf '%s  %s\n' "$sha" "$archive" | sha256sum -c
# Extract the one expected file, without trusting paths from the archive.
tar -xOzf "$archive" starship > "$out/bin/starship.tmp"
chmod 755 "$out/bin/starship.tmp"
mv "$out/bin/starship.tmp" "$out/bin/starship"
"$out/bin/starship" --version

# Source archives are pinned by tag and hash; builds remain inside build/.
build_source() {
  local name=$1 tag=$2 checksum=$3 url=$4 archive
  archive=$out/downloads/$name-$tag.tar.gz
  if [ ! -f "$archive" ] || ! printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c --status; then
    curl -fL "$url" -o "$archive.part"
    printf '%s  %s\n' "$checksum" "$archive.part" | sha256sum -c
    mv "$archive.part" "$archive"
  fi
  printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c
  mkdir -p "$out/src/$name-$tag"
  tar -xzf "$archive" -C "$out/src/$name-$tag" --strip-components=1
}
build_source hyprpicker 0.4.7 cde02b92abe372187c9d59a7cb2ca07ede5c3e1a8c81ed8b209dc0d3ac5f0339 \
  https://codeload.github.com/hyprwm/hyprpicker/tar.gz/refs/tags/v0.4.7
cmake -S "$out/src/hyprpicker-0.4.7" -B "$out/src/hyprpicker-0.4.7/build" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$out/src/hyprpicker-0.4.7/build" --parallel 2
install -m 755 "$out/src/hyprpicker-0.4.7/build/hyprpicker" "$out/bin/hyprpicker"
build_source mpvpaper 1.9 6de941b54941cfd5d00bac62d10ef47c1338f237dac4c78a7185d0f8d30cd4d1 \
  https://codeload.github.com/GhostNaN/mpvpaper/tar.gz/refs/tags/1.9
if [ ! -f "$out/src/mpvpaper-1.9/build/build.ninja" ]; then
  meson setup "$out/src/mpvpaper-1.9/build" "$out/src/mpvpaper-1.9" --buildtype release
fi
meson compile -C "$out/src/mpvpaper-1.9/build" -j 2
install -m 755 "$out/src/mpvpaper-1.9/build/mpvpaper" "$out/src/mpvpaper-1.9/build/mpvpaper-holder" "$out/bin/"

# Hyprsunset's matching Hyprlang and protocol definitions are private to the
# release; Fedora's older development package conflicts with Hyprland here.
build_source hyprlang 0.6.8 d10a0778b646e04d83e8b90cc0f764fb96958c01a15c3c0678d95a40fc647ed5 \
  https://codeload.github.com/hyprwm/hyprlang/tar.gz/refs/tags/v0.6.8
cmake -S "$out/src/hyprlang-0.6.8" -B "$out/src/hyprlang-0.6.8/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$out" -DCMAKE_INSTALL_LIBDIR=lib64 -DBUILD_TESTING=OFF
cmake --build "$out/src/hyprlang-0.6.8/build" --parallel 2
cmake --install "$out/src/hyprlang-0.6.8/build"
protocol_rev=1cb6db5fd6bb8aee419f4457402fa18293ace917
build_source hyprprotocols "$protocol_rev" 66d43275bc0e5d00204d37ba0e6b8b4f28cc9b15e4e241832d024e0d2cef9f14 \
  "https://codeload.github.com/hyprwm/hyprland-protocols/tar.gz/$protocol_rev"
cmake -S "$out/src/hyprprotocols-$protocol_rev" -B "$out/src/hyprprotocols-$protocol_rev/build" -G Ninja \
  -DCMAKE_INSTALL_PREFIX="$out" -DCMAKE_INSTALL_LIBDIR=lib64
cmake --install "$out/src/hyprprotocols-$protocol_rev/build"
build_source hyprsunset 0.4.0 5980e65ec650010e36c52e5f5acc0df9fd2d20051c63b89305bdc13276f237a6 \
  https://codeload.github.com/hyprwm/hyprsunset/tar.gz/refs/tags/v0.4.0
PKG_CONFIG_PATH="$out/share/pkgconfig:$out/lib64/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}" \
  cmake -S "$out/src/hyprsunset-0.4.0" -B "$out/src/hyprsunset-0.4.0/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON -DCMAKE_INSTALL_RPATH='$ORIGIN/../lib64'
cmake --build "$out/src/hyprsunset-0.4.0/build" --parallel 2
install -m 755 "$out/src/hyprsunset-0.4.0/build/hyprsunset" "$out/bin/"

# SongRec is only needed as a CLI client; its upstream Cargo.lock pins crates.
build_source songrec 0.8.0 abd2cc74a31c8eb63a5d38c2dee24f56dd559b1fd4cab50d82b66a4b9e164eda \
  https://codeload.github.com/marin-m/SongRec/tar.gz/refs/tags/0.8.0
(
  cd "$out/src/songrec-0.8.0"
  CARGO_HOME="$out/cargo" cargo build --release --locked --no-default-features --features pulse,pipewire -j 2
)
install -m 755 "$out/src/songrec-0.8.0/target/release/songrec" "$out/bin/"
