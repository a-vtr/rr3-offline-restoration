"""Run the original native host harness using generated, non-game resources.

Requires macOS and Apple developer tools. No account, signing, device or game data.
Temporary inputs, binaries and diagnostics are removed when this runner exits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asan', action='store_true')
    args = parser.parse_args()
    runner = Path(__file__).resolve().parents[1] / 'scripts/test_native_resources.py'
    with tempfile.TemporaryDirectory(prefix='rr3-native-synthetic-') as temporary:
        root = Path(temporary)
        seed = root / 'seed'
        manifest = []
        for index, name in enumerate(('Tracks/Test/high/sample.bin',
                                       'gui_assets/Test/sample.bin',
                                       'vehicles/Test/sample.bin')):
            content = (f'Synthetic resource {index}\n'.encode()) * 1024
            target = seed / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            manifest.append({'path': name, 'bytes': len(content),
                             'sha256': hashlib.sha256(content).hexdigest()})
        report = root / 'report.json'
        report.write_text(json.dumps({'manifest': manifest}))
        command = [sys.executable, str(runner), str(seed), str(report), str(root / 'run')]
        if args.asan:
            command.append('--asan')
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            for name in ('build.txt', 'run.txt'):
                path = root / 'run' / name
                if path.exists():
                    print(path.read_text(), file=sys.stderr)
            print(result.stderr, file=sys.stderr)
        else:
            print('PASS: native macOS restoration/lifecycle harness with synthetic resources'
                  + (' (AddressSanitizer)' if args.asan else ''))
        return result.returncode


if __name__ == '__main__':
    sys.exit(main())
