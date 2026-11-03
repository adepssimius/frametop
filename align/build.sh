#!/usr/bin/env bash
# Build ft-align in the dev container on the Frame (align/build/ft-align), and its unit test.
# It runs in the container too: scripts/in-box. It reads ft-camd's ring, so hand tracking's ft-camd has to
# be built, with its capabilities (hands/run.sh caps).
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
"$root/scripts/sync.sh" >/dev/null
exec "$root/scripts/frame.sh" -C align 'set -e; mkdir -p build/include
. ../scripts/openvr.sh
stb=2c980bb59875b0d32144a71867fbdebb2f77cd20
[ -f build/include/stb-$stb ] || { curl -fsSL "https://raw.githubusercontent.com/nothings/stb/$stb/stb_truetype.h" -o build/include/stb_truetype.h; touch build/include/stb-$stb; }
cxx="g++ -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter -Wno-psabi"
make -s -C ../hands build/ft-camd
$cxx -o build/solver-test tests/solver_test.cpp solver.cpp ../hands/track/calib.cpp -ljsoncpp -lpthread
build/solver-test
echo "align/tests/solver_test.cpp: ok"
$cxx -Ibuild/include $(pkg-config --cflags gbm libdrm) -o build/ft-align main.cpp hud.cpp solver.cpp ../screens/overlaytex.cpp ../hands/track/calib.cpp \
    -ljsoncpp $(pkg-config --libs apriltag gbm) $OPENVR_LIBS -lpthread
echo "built build/ft-align"'
