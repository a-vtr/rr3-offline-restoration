"""Read-only IPA component/signature/layout audit; private output, no extraction.

Parses signature metadata and ordinary code-page hashes; does not establish trust.
Dependency resolution is a static packaging check, not a dyld/runtime simulation.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import posixpath
import struct
import zipfile

from inspect_ipa import macho_header
from preservation_baseline import signature, write_json


def cstring(data, offset):
    return data[offset:].split(b'\0')[0].decode(errors='replace') if 0 < offset < len(data) else None


def signing_metadata(data):
    if len(data) < 12:
        return {'error': 'No complete signature header'}
    magic, size, count = struct.unpack_from('>III', data)
    if magic != 0xfade0cc0 or size > len(data) or count > 100:
        return {'error': 'Unexpected embedded signature layout', 'magic': hex(magic)}
    result = {'length': size, 'slots': [], 'code_directories': []}
    for index in range(count):
        slot, offset = struct.unpack_from('>II', data, 12 + index * 8)
        if offset + 8 > size:
            raise ValueError('Invalid signature slot offset')
        kind, length = struct.unpack_from('>II', data, offset)
        if length < 8 or offset + length > size:
            raise ValueError('Invalid signature blob length')
        blob = data[offset:offset + length]
        result['slots'].append({'type': slot, 'magic': hex(kind), 'length': length})
        if kind == 0xfade0c02:
            version, flags, hash_offset, identifier_offset, special, code_slots, code_limit = struct.unpack_from('>7I', blob, 8)
            directory = {'version': hex(version), 'flags': flags, 'adhoc_flag': bool(flags & 2),
                         'identifier': cstring(blob, identifier_offset), 'code_slots': code_slots,
                         'special_slots': special, 'code_limit': code_limit,
                         'hash_size': blob[36], 'hash_type': blob[37], 'page_size_log2': blob[39]}
            if version >= 0x20200 and length >= 52:
                team_offset = struct.unpack_from('>I', blob, 48)[0]
                directory['team_identifier'] = cstring(blob, team_offset)
            result['code_directories'].append(directory)
        if kind == 0xfade7171:
            result['entitlements'] = plistlib.loads(blob[8:])
        if slot == 0x10000:
            result['cms_payload_bytes'] = length - 8
    return result


def verify_code_pages(archive, name, signature_blob):
    """Compare ordinary signed pages to embedded hashes, not certificate trust."""
    _, length, count = struct.unpack_from('>III', signature_blob)
    groups = collections.defaultdict(list)
    results = []
    for i in range(count):
        slot, offset = struct.unpack_from('>II', signature_blob, 12 + i * 8)
        magic, size = struct.unpack_from('>II', signature_blob, offset)
        if magic != 0xfade0c02:
            continue
        blob = signature_blob[offset:offset + size]
        version, _, hash_offset, _, _, slots, limit = struct.unpack_from('>7I', blob, 8)
        hash_size, kind, _, page_log2 = struct.unpack_from('4B', blob, 36)
        scatter = struct.unpack_from('>I', blob, 44)[0] if version >= 0x20100 else 0
        algorithms = {1: 'sha1', 2: 'sha256', 3: 'sha256', 4: 'sha384'}
        result = {'slot': slot, 'hash_type': kind, 'code_limit': limit, 'code_slots': slots,
                  'mismatch_count': 0, 'first_mismatched_pages': []}
        results.append(result)
        page_size = 1 << page_log2 if page_log2 else limit
        if (scatter or kind not in algorithms or not page_size or limit > archive.getinfo(name).file_size
                or slots != (limit + page_size - 1) // page_size
                or hash_offset + slots * hash_size > len(blob)):
            result['status'] = 'unsupported_or_inconsistent_directory'
            continue
        groups[page_size].append((result, blob, hash_offset, hash_size, algorithms[kind]))
    for page_size, directories in groups.items():
        with archive.open(name) as stream:
            for index in range(max(d[0]['code_slots'] for d in directories)):
                chunk = stream.read(page_size)
                for result, blob, offset, size, algorithm in directories:
                    if index >= result['code_slots']:
                        continue
                    amount = min(page_size, result['code_limit'] - index * page_size)
                    actual = hashlib.new(algorithm, chunk[:amount]).digest()[:size]
                    recorded = blob[offset + index * size:offset + (index + 1) * size]
                    if actual != recorded:
                        result['mismatch_count'] += 1
                        if len(result['first_mismatched_pages']) < 20:
                            result['first_mismatched_pages'].append(index)
        for result, *_ in directories:
            result['status'] = 'match' if result['mismatch_count'] == 0 else 'mismatch'
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ipa', type=Path)
    parser.add_argument('reports', type=Path)
    args = parser.parse_args()
    ipa, reports = args.ipa.resolve(), args.reports.resolve()
    repo = Path(__file__).resolve().parents[1]
    if reports.is_relative_to(repo) or reports.is_relative_to(ipa.parent):
        parser.error('reports must be private and outside repository/source')
    os.umask(0o077)
    before = signature(ipa.stat())
    old = json.loads((reports / 'ipa-inspection.json').read_text())
    if old['source_signature'] != before:
        raise ValueError('IPA metadata changed since baseline')
    result = {'source_signature': before, 'signature_trust_verified': False}
    prior = {}
    previous_path = reports / 'standalone-audit.json'
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        if previous.get('source_signature') == before and previous.get('source_unchanged'):
            prior = previous.get('components', {})
    components = {}
    bundles = []
    with zipfile.ZipFile(ipa) as archive:
        entries = {e.filename: e for e in archive.infolist()}
        for name, entry in entries.items():
            if not name.startswith('Payload/') or not name.endswith('/Info.plist') or entry.file_size > 2 * 1024 * 1024:
                continue
            info = plistlib.loads(archive.read(name))
            executable = info.get('CFBundleExecutable')
            if not executable:
                continue
            folder = posixpath.dirname(name)
            target = folder + '/' + executable
            if target not in entries:
                continue
            bundles.append({'path': folder, 'identifier': info.get('CFBundleIdentifier'),
                            'version': info.get('CFBundleShortVersionString'),
                            'minimum_ios': info.get('MinimumOSVersion'), 'executable': target,
                            'package_type': info.get('CFBundlePackageType')})
            components[target] = {'bundle': folder, 'bundle_identifier': info.get('CFBundleIdentifier')}
        for name in entries:
            if name.startswith('Payload/') and name.endswith('.dylib'):
                components.setdefault(name, {})
        result['bundles'] = bundles
        main = next(b for b in bundles if b['package_type'] == 'APPL')
        for name, component in components.items():
            with archive.open(name) as stream:
                header = macho_header(stream.read(1024 * 1024))
                component['macho'] = header
                cs = header.get('code_signature')
                if cs:
                    if cs['size'] > 16 * 1024 * 1024 or cs['offset'] + cs['size'] > entries[name].file_size:
                        raise ValueError('Invalid/oversized code signature')
                    cached = prior.get(name, {})
                    if cached.get('macho', {}).get('code_signature') == cs and cached.get('code_page_checks'):
                        component['signing'] = cached['signing']
                        component['code_page_checks'] = cached['code_page_checks']
                        component['reused_signature_page_checks'] = True
                    else:
                        stream.seek(cs['offset'])
                        blob = stream.read(cs['size'])
                        component['signing'] = signing_metadata(blob)
                        if 'error' not in component['signing']:
                            component['code_page_checks'] = verify_code_pages(archive, name, blob)
            # Framework/library runpaths can inherit the main executable's runpaths.
        main_rpaths = components[main['executable']]['macho'].get('rpaths', [])
        for name, component in components.items():
            header = component['macho']
            app_executable = main['executable']
            # Extensions use their own @executable_path root.
            for bundle in bundles:
                if bundle['package_type'] == 'XPC!' and name.startswith(bundle['path'] + '/'):
                    app_executable = bundle['executable']
            def expand(value):
                return posixpath.normpath(value.replace('@loader_path', posixpath.dirname(name)).replace('@executable_path', posixpath.dirname(app_executable)))
            rpaths = header.get('rpaths', []) + main_rpaths
            checks = []
            for dep in header.get('dependencies', []):
                if dep.startswith(('/System/', '/usr/lib/')):
                    continue
                candidates = [expand(dep)]
                if dep.startswith('@rpath/'):
                    candidates = [posixpath.join(expand(path), dep[len('@rpath/'):]) for path in rpaths]
                system_candidates = [c for c in candidates if c.startswith(('/usr/lib/', '/System/'))]
                checks.append({'dependency': dep, 'candidates': candidates,
                               'present_candidates': [c for c in candidates if c in entries],
                               'platform_runtime_candidates': system_candidates})
            component['non_system_dependency_checks'] = checks
        result['components'] = components
        result['provisioning_entries'] = [n for n in entries if n.endswith('.mobileprovision')]
        result['entitlement_sidecars'] = [n for n in entries if n.endswith('.xcent')]
        result['livecontainer_named_entries'] = [n for n in entries if 'livecontainer' in n.lower()]
    result['source_unchanged'] = signature(ipa.stat()) == before
    result['summary'] = {
        'executable_components': len(components), 'bundles_with_executables': len(bundles),
        'architecture_counts': dict(collections.Counter(c['macho'].get('architecture', 'other/fat') for c in components.values())),
        'encryption_id_counts': dict(collections.Counter(str(c['macho'].get('encryption', {}).get('cryptid', 'no_command')) for c in components.values())),
        'components_with_signature': sum('signing' in c for c in components.values()),
        'components_with_adhoc_flag': sum(any(d['adhoc_flag'] for d in c.get('signing', {}).get('code_directories', [])) for c in components.values()),
        'unresolved_non_system_dependency_references': sum(not d['present_candidates'] and not d['platform_runtime_candidates'] for c in components.values() for d in c['non_system_dependency_checks']),
        'platform_runtime_dependency_references': sum(not d['present_candidates'] and bool(d['platform_runtime_candidates']) for c in components.values() for d in c['non_system_dependency_checks']),
        'components_with_matching_code_pages': sum(bool(c.get('code_page_checks')) and all(d['status'] == 'match' for d in c['code_page_checks']) for c in components.values()),
        'components_with_mismatched_code_pages': sum(any(d['status'] == 'mismatch' for d in c.get('code_page_checks', [])) for c in components.values()),
    }
    write_json(reports / 'standalone-audit.json', result)
    print(json.dumps(result['summary']))
    print('Source unchanged:', result['source_unchanged'])
    primary = components[main['executable']]
    print('Main entitlement keys:', sorted(primary.get('signing', {}).get('entitlements', {})))


if __name__ == '__main__':
    main()
