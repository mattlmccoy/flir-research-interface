#!/usr/bin/env bash
# One-shot PySpin/Spinnaker diagnostics for Linux. Re-applies the (idempotent) executable-stack
# clear, then prints everything needed to debug an import failure. Paste the WHOLE output back.
#   bash ~/flir-research-interface/scripts/fri-linux-doctor.sh
FRI_HOME="${FRI_HOME:-$HOME/flir-research-interface}"
cd "$FRI_HOME/backend" 2>/dev/null || { echo "no checkout at $FRI_HOME"; exit 1; }

echo "### 0. clear executable stack (idempotent, needs sudo)"
sudo python3 "$FRI_HOME/scripts/clear_execstack.py" /opt/spinnaker/lib/*.so* 2>&1

echo
echo "### 1. import PySpin the way the operator does (lazy binding)"
uv run python -c "from flir_research_interface.sdk_install import pyspin_importable; ok,detail=pyspin_importable(); print('PySpin OK' if ok else 'FAILED', '-', detail)" 2>&1

echo
echo "### 2. loader path for spinnaker"
ldconfig -p | grep -i spinnaker || echo "(nothing in ldconfig cache)"

echo
echo "### 3. GNU_STACK flags on /opt/spinnaker/lib (want a '-', not 'X')"
python3 - <<'PY'
import glob, struct, os
PT = 0x6474e551
for f in sorted(glob.glob('/opt/spinnaker/lib/*.so*')):
    try:
        d = open(f, 'rb').read(8192)
    except OSError:
        continue
    if d[:4] != b'\x7fELF':
        continue
    end = '<' if d[5] == 1 else '>'
    e_phoff = struct.unpack_from(end + 'Q', d, 0x20)[0]
    ps = struct.unpack_from(end + 'H', d, 0x36)[0]
    pn = struct.unpack_from(end + 'H', d, 0x38)[0]
    for i in range(pn):
        off = e_phoff + i * ps
        if off + 8 > len(d):
            break
        if struct.unpack_from(end + 'I', d, off)[0] == PT:
            fl = struct.unpack_from(end + 'I', d, off + 4)[0]
            print(('X' if fl & 1 else '-'), os.path.basename(f))
PY

echo
echo "### 4. SELinux mode + recent denials"
getenforce 2>/dev/null || echo "(no SELinux)"
sudo ausearch -m avc -ts recent 2>/dev/null | grep -iE 'execstack|execmod|textrel|spinnaker' | tail -8 \
  || echo "(no matching AVC denials or ausearch unavailable)"

echo
echo "### 5. missing shared-object deps (the _PySpin extension + libSpinVideo)"
ext="$(find "$FRI_HOME/backend/.venv" -name '_PySpin*.so' 2>/dev/null | head -1)"
echo "extension: ${ext:-not found}"
[ -n "$ext" ] && { ldd "$ext" 2>&1 | grep -iE 'not found' || echo "  _PySpin: (no 'not found' deps)"; }
ldd /opt/spinnaker/lib/libSpinVideo.so 2>&1 | grep -iE 'not found' \
  || echo "  libSpinVideo: (no 'not found' deps)"

echo
echo "### 6. environment"
uname -m
. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"
uv run python --version 2>&1
