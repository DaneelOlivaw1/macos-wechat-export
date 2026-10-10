#!/usr/bin/env python3
"""Explicit temporary-copy bootstrap. Never changes original signatures or SIP."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess as sp
import sys
import time


def emit(kind, **items):
    print(json.dumps(dict(type=kind, **items)), flush=True)


def run(args):
    result = sp.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('command_failed: ' + Path(args[0]).name)
    return result.stdout or result.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app', type=Path, default=Path('/Applications/WeChat.app'))
    ap.add_argument('--db-root', type=Path)
    ap.add_argument('--state-dir', type=Path, default=Path('.wechat-local'))
    ap.add_argument('--timeout', type=int, default=180)
    ap.add_argument('--acknowledge-debug-copy', action='store_true')
    args = ap.parse_args()
    if not args.acknowledge_debug_copy:
        ap.error('Read README first; requires --acknowledge-debug-copy. Quit WeChat normally before running.')
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('bootstrap supports native Apple Silicon macOS only; do not run under Rosetta')
    if os.geteuid() == 0:
        raise RuntimeError('do not run with sudo or as root')
    if sp.run(['pgrep', '-x', 'WeChat'], capture_output=True).returncode == 0:
        raise RuntimeError('quit WeChat normally first; no processes were stopped')
    app = args.app.resolve(strict=True)
    root = args.db_root
    if root is None:
        roots = list((Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files').glob('*/db_storage'))
        if len(roots) != 1:
            raise RuntimeError('specify --db-root: expected exactly one account')
        root = roots[0]
    root = root.resolve(strict=True)
    if not list(root.rglob('*.db')):
        raise RuntimeError('no databases; log into original WeChat at least once first')
    state = args.state_dir.resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(state, 0o700)
    keys = state/'keys.json'
    shadow = state/'WeChat-trial.app'
    disabled = state/'WeChat-trial.disabled'
    if keys.exists() or shadow.exists() or disabled.exists():
        raise RuntimeError('state contains a previous bootstrap; use a new --state-dir, never overwrite live keys')
    os.umask(0o077)
    original_signature = run(['codesign', '-dvv', str(app)])
    (state/'original-signature.txt').write_text(original_signature)
    original_exe = app/'Contents/MacOS/WeChat'
    run(['codesign', '--verify', '--deep', '--strict', str(app)])
    lldb_python = run(['/usr/bin/lldb', '-P']).strip()
    env = dict(os.environ, PYTHONPATH=lldb_python)
    run(['/usr/bin/ditto', str(app), str(shadow)])
    run(['codesign', '--force', '--deep', '--sign', '-', str(shadow)])
    run(['codesign', '--verify', '--deep', '--strict', str(shadow)])
    emit('copy_prepared', instruction='In the temporary WeChat window, choose Enter Weixin and finish phone login if requested.')
    rc = 2
    try:
        command = ['/usr/bin/python3', str(Path(__file__).with_name('capture_keys.py')),
                   '--exe', str(shadow/'Contents/MacOS/WeChat'), '--db-root', str(root),
                   '--out', str(keys), '--timeout', str(args.timeout)]
        # Capture subprocess inherits the terminal for metadata only, never secrets.
        proc = sp.Popen(command, env=env)
        try:
            rc = proc.wait()
        except KeyboardInterrupt:
            # Terminal sends SIGINT to both. Give capture its finally block before restoring.
            proc.wait(timeout=15)
            rc = 130
    finally:
        if run(['codesign', '-dvv', str(app)]) != original_signature:
            raise RuntimeError('original signature changed unexpectedly; restore manually')
        running = sp.run(['pgrep', '-x', 'WeChat'], capture_output=True, text=True).stdout.split()
        commands = [run(['ps', '-p', pid, '-o', 'comm=']).strip() for pid in running]
        if any(str(shadow) in command for command in commands):
            emit('manual_restore_required', reason='temporary process is still running; quit it normally, then open original')
        else:
            ls = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
            sp.run([ls, '-u', str(shadow)], capture_output=True)
            shadow.rename(disabled)
            if not commands:
                # Exact executable avoids LaunchServices confusing identical bundle IDs.
                restored = sp.Popen([str(original_exe)], stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=True)
                time.sleep(1)
                emit('original_launch_requested', pid=restored.pid, exited=restored.poll() is not None)
            emit('original_signature_unchanged', temporary_bundle_disabled=True)
    if keys.exists():
        count = len(json.loads(keys.read_text())['keys'])
        emit('keys_saved_privately', verified_databases=count, permissions=oct(keys.stat().st_mode & 0o777))
    return rc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        emit('bootstrap_error', reason=str(error))
        sys.exit(2)
