#!/usr/bin/env python3
"""Synthetic FinderInfo regression; never touches the installed WeChat."""
import plistlib
from pathlib import Path
import subprocess as sp
import tempfile

from bootstrap_keys import clear_finder_info


def main():
    attribute = 'com.apple.FinderInfo'
    with tempfile.TemporaryDirectory(prefix='finderinfo-check-') as directory:
        root = Path(directory)
        app = root/'Synthetic.app'
        (app/'Contents/MacOS').mkdir(parents=True)
        (app/'Contents/Resources').mkdir()
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'local.synthetic.finderinfo',
            'CFBundleExecutable': 'synthetic', 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': '1'}))
        source = root/'synthetic.c'
        source.write_text('int main(void) { return 0; }\n')
        sp.run(['xcrun', 'clang', str(source), '-o', str(app/'Contents/MacOS/synthetic')], check=True)
        readonly = app/'Contents/Resources/readonly'
        readonly.write_text('synthetic')
        readonly.chmod(0o444)
        outside = root/'outside'
        outside.write_text('synthetic')
        (app/'Contents/outside-link').symlink_to(outside)
        outside_dir = root/'outside-dir'
        outside_dir.mkdir()
        (app/'Contents/outside-dir-link').symlink_to(outside_dir)
        for path in (app, outside, outside_dir):
            sp.run(['/usr/bin/xattr', '-w', '-x', attribute,
                    '00'*8+'2000'+'00'*22, str(path)], check=True)
        sp.run(['/usr/bin/xattr', '-w', 'local.synthetic.keep', 'keep', str(app)], check=True)
        failed = sp.run(['codesign', '--force', '--deep', '--sign', '-', str(app)],
                        capture_output=True, text=True)
        assert failed.returncode != 0 and 'detritus' in failed.stderr
        clear_finder_info(app)
        assert attribute not in sp.check_output(['/usr/bin/xattr', str(app)], text=True).splitlines()
        assert attribute in sp.check_output(['/usr/bin/xattr', str(outside)], text=True).splitlines()
        assert attribute in sp.check_output(['/usr/bin/xattr', str(outside_dir)], text=True).splitlines()
        assert sp.check_output(['/usr/bin/xattr', '-p', 'local.synthetic.keep', str(app)], text=True).strip() == 'keep'
        assert readonly.stat().st_mode & 0o777 == 0o444
        clear_finder_info(app)  # No FinderInfo is also safe, including readonly files.
        # The external symlink tests cleanup isolation; omit it from signature validation.
        (app/'Contents/outside-link').unlink()
        (app/'Contents/outside-dir-link').unlink()
        sp.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        sp.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    print('PASS: FinderInfo signing fix, readonly files, unrelated attrs, symlink isolation')


if __name__ == '__main__':
    main()
