"""Build/run the native macOS lab, not RR3 or an iPadOS app. No signing command.

Use the existing small sample seed/report. All generated outputs stay outside repo.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from datetime import datetime, timezone


def host_build_context():
    def tool(*command):
        return subprocess.run(command, capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()
    return {'host_os': platform.system(), 'host_os_version': platform.mac_ver()[0],
            'host_architecture': platform.machine(), 'build_target': 'macOS host lab',
            'sdk_name': 'macosx',
            'sdk_version': tool('xcrun', '--sdk', 'macosx', '--show-sdk-version'),
            'compiler': tool('xcrun', '--sdk', 'macosx', 'clang++', '--version').splitlines()[0]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('seed', type=Path)
    p.add_argument('sample_report', type=Path)
    p.add_argument('output', type=Path, help='New private directory outside repository')
    p.add_argument('--asan', action='store_true')
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    seed, report, output = a.seed.resolve(), a.sample_report.resolve(), a.output.resolve()
    if (output.is_relative_to(repo) or output.is_relative_to(seed)
            or seed.is_relative_to(output) or output.exists()):
        p.error('output must be new, external, and separate from seed')
    os.umask(0o077)
    output.mkdir(mode=0o700)
    executable = output / 'resource-harness'
    sources = [repo / 'native/RRResourceRuntime.mm', repo / 'tests/native_resource_harness.mm']
    command = ['xcrun', '--sdk', 'macosx', 'clang++', '-std=c++17', '-fobjc-arc',
               '-fblocks', '-Wno-deprecated-declarations', '-Wall', '-Wextra', '-Werror',
               '-I', str(repo / 'native'), *map(str, sources), '-framework', 'Foundation',
               '-o', str(executable)]
    if a.asan:
        command[4:4] = ['-g', '-fsanitize=address']
    build = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (output / 'build.txt').write_text(build.stdout + build.stderr)
    result = {'result_schema_version': 1, 'harness_contract_version': 1,
              'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'run_id': output.name,
              'scope': 'native macOS host lab; no iPadOS/RR3 execution',
              'environment': host_build_context(),
              'asan': a.asan, 'build_exit': build.returncode,
              'source_sha256': {str(s.relative_to(repo)): hashlib.sha256(s.read_bytes()).hexdigest()
                                for s in [*sources, repo / 'native/RRResourceRuntime.h', Path(__file__).resolve()]}}
    if build.returncode == 0:
        run = subprocess.run([str(executable), str(seed), str(report), str(output / 'scratch')],
                             capture_output=True, text=True, timeout=30)
        (output / 'run.txt').write_text(run.stdout + run.stderr)
        result['run_exit'] = run.returncode
        result['passed'] = run.returncode == 0 and 'ALL NATIVE HOST TESTS PASSED' in run.stdout
    else:
        result['passed'] = False
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha256'}))
    if not result['passed']:
        raise SystemExit('Native host lab failed; private build/run evidence retained.')


if __name__ == '__main__':
    main()
