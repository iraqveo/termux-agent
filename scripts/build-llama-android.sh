#!/usr/bin/env bash
set -euo pipefail

# Build llama.cpp for Android ARM64 when an Android NDK is available.
# Usage: ANDROID_NDK=/path/to/ndk ./scripts/build-llama-android.sh [source-dir] [output-dir]

SOURCE_DIR="${1:-${HOME}/llama.cpp}"
OUTPUT_DIR="${2:-${HOME}/.termux-agent/bin}"
NDK="${ANDROID_NDK:-${ANDROID_NDK_HOME:-}}"

if [[ -z "$NDK" || ! -d "$NDK" ]]; then
  echo 'Set ANDROID_NDK to an installed Android NDK directory.' >&2
  exit 2
fi
if [[ ! -f "$SOURCE_DIR/CMakeLists.txt" ]]; then
  echo "llama.cpp source was not found at $SOURCE_DIR" >&2
  exit 2
fi

BUILD_DIR="$SOURCE_DIR/build-android-arm64"
cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-26 \
  -DGGML_OPENMP=OFF \
  -DGGML_NATIVE=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --config Release --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"

mkdir -p "$OUTPUT_DIR"
find "$BUILD_DIR" -type f -perm -111 -name 'llama-*' -exec cp {} "$OUTPUT_DIR" \;
chmod 0755 "$OUTPUT_DIR"/llama-* 2>/dev/null || true
cat <<'EOF'
Build complete. For mobile inference, prefer a GGUF Q4_K_M model and keep context bounded, for example:
  -c 4096
Set LD_LIBRARY_PATH to the directory containing the copied binaries before launching them.
EOF
