#!/bin/sh
# Build a sample release tree with real x86-64 ELF64 objects.
set -eu
CC=${CC:-gcc}
OUT="$(cd "$(dirname "$0")" && pwd)/release"
SRC="$OUT/src"
rm -rf "$OUT"
mkdir -p "$SRC" "$OUT/app/bin" "$OUT/app/lib" "$OUT/app/lib2"

cat > "$SRC/foo.c" <<'EOF'
int foo_v1(void) { return 1; }
int foo_v2(void) { return 2; }
EOF
cat > "$SRC/foo.map" <<'EOF'
FOO_1.0 { global: foo_v1; };
FOO_2.0 { global: foo_v2; } FOO_1.0;
EOF
$CC -shared -fPIC -o "$OUT/app/lib/libfoo.so.1" "$SRC/foo.c" \
    -Wl,-soname,libfoo.so.1 -Wl,--version-script="$SRC/foo.map"
ln -sf libfoo.so.1 "$OUT/app/lib/libfoo.so"

# stub libc so the release tree is self-contained for the precheck
cat > "$SRC/libc.map" <<'EOF'
GLIBC_2.2.5 { global: *; };
GLIBC_2.34 { } GLIBC_2.2.5;
EOF
cat > "$SRC/libc.c" <<'EOF'
void __libc_start_main(void) {}
EOF
$CC -shared -fPIC -o "$OUT/app/lib/libc.so.6" "$SRC/libc.c" \
    -Wl,-soname,libc.so.6 -Wl,--version-script="$SRC/libc.map"

cat > "$SRC/bar.c" <<'EOF'
extern int foo_v1(void);
int bar(void) { return foo_v1(); }
EOF
# libbar: needs libfoo.so.1, RUNPATH $ORIGIN (only used for direct deps)
$CC -shared -fPIC -o "$OUT/app/lib/libbar.so" "$SRC/bar.c" \
    -L"$OUT/app/lib" -lfoo \
    -Wl,-soname,libbar.so -Wl,--enable-new-dtags -Wl,-rpath,'$ORIGIN'

cat > "$SRC/baz.c" <<'EOF'
int baz(void) { return 3; }
EOF
# libbaz lives in lib2, found only via the entry's RPATH (inherited chain)
$CC -shared -fPIC -o "$OUT/app/lib2/libbaz.so" "$SRC/baz.c" \
    -Wl,-soname,libbaz.so

cat > "$SRC/qux.c" <<'EOF'
extern int baz(void);
int qux(void) { return baz(); }
EOF
# libqux has no rpath; its dep libbaz.so resolves via app's RPATH chain
$CC -shared -fPIC -o "$OUT/app/lib/libqux.so" "$SRC/qux.c" \
    -L"$OUT/app/lib2" -lbaz -Wl,-soname,libqux.so

cat > "$SRC/main.c" <<'EOF'
extern int bar(void);
extern int qux(void);
extern int foo_v2(void);
int main(void) { return bar() + qux() + foo_v2(); }
EOF
# entry: RPATH $ORIGIN/../lib:$ORIGIN/../lib2 (DT_RPATH, inherited)
$CC -o "$OUT/app/bin/app" "$SRC/main.c" \
    -L"$OUT/app/lib" -lbar -lqux -L"$OUT/app/lib2" -lfoo \
    -Wl,--disable-new-dtags -Wl,-rpath,'$ORIGIN/../lib:$ORIGIN/../lib2'

# broken consumer: requires FOO_9.9 which libfoo does not define
cat > "$SRC/foo9.map" <<'EOF'
FOO_9.9 { global: foo_v9; };
EOF
cat > "$SRC/need9.c" <<'EOF'
extern int foo_v1(void);
int need9(void) { return foo_v1(); }
EOF
$CC -shared -fPIC -o "$SRC/libfoo9tmp.so" "$SRC/need9.c" \
    -L"$OUT/app/lib" -lfoo -Wl,-soname,libneed9.so
# relink against a stub that only provides FOO_9.9 to forge the VERNEED
cat > "$SRC/foostub.c" <<'EOF'
int foo_v9(void) { return 9; }
EOF
$CC -shared -fPIC -o "$SRC/libfoostub.so" "$SRC/foostub.c" \
    -Wl,-soname,libfoo.so.1 -Wl,--version-script="$SRC/foo9.map"
cat > "$SRC/need9b.c" <<'EOF'
extern int foo_v9(void);
int need9(void) { return foo_v9(); }
EOF
$CC -shared -fPIC -o "$OUT/app/lib/libneed9.so" "$SRC/need9b.c" \
    -L"$SRC" -lfoostub -Wl,-soname,libneed9.so

# missing dependency case: libghostneed needs libghost.so, which is absent
# from the release tree (its stub stays in src/, outside any search dir)
cat > "$SRC/ghost.c" <<'EOF'
int ghost(void) { return 0; }
EOF
$CC -shared -fPIC -o "$SRC/libghost.so" "$SRC/ghost.c" -Wl,-soname,libghost.so
cat > "$SRC/ghostneed.c" <<'EOF'
extern int ghost(void);
int use_ghost(void) { return ghost(); }
EOF
$CC -shared -fPIC -o "$OUT/app/lib/libghostneed.so" "$SRC/ghostneed.c" \
    -L"$SRC" -lghost -Wl,-soname,libghostneed.so

cat > "$SRC/main2.c" <<'EOF'
extern int need9(void);
extern int bar(void);
extern int use_ghost(void);
int main(void) { return need9() + bar() + use_ghost(); }
EOF
$CC -o "$OUT/app/bin/app_bad" "$SRC/main2.c" \
    -L"$OUT/app/lib" -lneed9 -lbar -lghostneed \
    -Wl,--disable-new-dtags -Wl,-rpath,'$ORIGIN/../lib' \
    -Wl,--allow-shlib-undefined

# symlink loop and escape
ln -sf loop.so "$OUT/app/lib/loop.so"
ln -sf /etc/hostname "$OUT/app/lib/escape.so"

# non-x86-64 / invalid file
echo "not an elf" > "$OUT/app/lib/notelf.so"

echo "release tree: $OUT"
