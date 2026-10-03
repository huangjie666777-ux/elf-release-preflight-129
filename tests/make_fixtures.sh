#!/usr/bin/env bash
# Build a sample release tree of real x86-64 ELF objects for testing.
set -euo pipefail
OUT="${1:-/tmp/precheck-release}"
SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"' EXIT

cat > "$SRC/foo.c" <<'EOF'
int foo1(void) { return 1; }
int foo2(void) { return 2; }
EOF
cat > "$SRC/foo.map" <<'EOF'
LIBFOO_1 { global: foo1; };
LIBFOO_2 { global: foo2; } LIBFOO_1;
EOF
cat > "$SRC/foo_old.map" <<'EOF'
LIBFOO_1 { global: foo1; };
EOF
cat > "$SRC/bar.c" <<'EOF'
extern int foo1(void);
int bar(void) { return foo1(); }
EOF
cat > "$SRC/main.c" <<'EOF'
extern int foo2(void);
extern int bar(void);
int main(void) { return foo2() + bar(); }
EOF

rm -rf "$OUT"
mkdir -p "$OUT/bin" "$OUT/lib" "$OUT/oldlib" "$OUT/plugins"

gcc -shared -fPIC -o "$OUT/lib/libfoo.so.1.0" "$SRC/foo.c" \
    -Wl,--version-script="$SRC/foo.map" -Wl,-soname,libfoo.so.1
ln -s libfoo.so.1.0 "$OUT/lib/libfoo.so.1"

gcc -shared -fPIC -o "$OUT/oldlib/libfoo.so.1" "$SRC/foo.c" \
    -Wl,--version-script="$SRC/foo_old.map" -Wl,-soname,libfoo.so.1

gcc -shared -fPIC -o "$OUT/lib/libbar.so" "$SRC/bar.c" \
    -L"$OUT/lib" -l:libfoo.so.1 \
    -Wl,-soname,libbar.so -Wl,--enable-new-dtags \
    -Wl,-rpath,'$ORIGIN'

gcc -o "$OUT/bin/app" "$SRC/main.c" \
    -L"$OUT/lib" -l:libfoo.so.1 -l:libbar.so \
    -Wl,--enable-new-dtags -Wl,-rpath,'$ORIGIN/../lib'

gcc -shared -fPIC -o "$OUT/plugins/libplug.so" "$SRC/bar.c" \
    -L"$OUT/lib" -l:libfoo.so.1 -Wl,-soname,libplug.so \
    -Wl,--disable-new-dtags -Wl,-rpath,'$ORIGIN/../lib'

ln -s /etc/hostname "$OUT/lib/evil-link"
ln -s loop-b "$OUT/lib/loop-a"
ln -s loop-a "$OUT/lib/loop-b"

echo "fixtures built at $OUT"

