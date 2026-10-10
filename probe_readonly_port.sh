#!/bin/bash
set -eu
case "${1:-}" in
  ""|--admin) ;;
  *) echo 'Usage: bash probe_readonly_port.sh [--admin]' >&2; exit 2 ;;
esac
probe_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
probe_build="$(mktemp -d "${TMPDIR:-/tmp}/wechat-readonly-probe.XXXXXX")"
trap 'rm -rf -- "$probe_build"' EXIT
xcrun clang -Wall -Wextra -Werror -O2 "$probe_dir/readonly_port_probe.c" -o "$probe_build/probe"
cat > "$probe_build/debugger.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.apple.security.cs.debugger</key><true/></dict></plist>
PLIST
codesign --force --sign - --entitlements "$probe_build/debugger.plist" "$probe_build/probe"
"$probe_build/probe" self
probe_pid="$(pgrep -x WeChat || true)"
if ! [[ "$probe_pid" =~ ^[0-9]+$ ]]; then
    echo 'Expected exactly one running WeChat process. Open the official app normally first.' >&2
    exit 2
fi
if [ "${1:-}" = --admin ]; then
    echo 'Administrator test: password entry is handled by macOS sudo, not by this program.'
    sudo -- "$probe_build/probe" "$probe_pid"
else
    "$probe_build/probe" "$probe_pid"
fi
