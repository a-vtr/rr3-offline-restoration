"""Compare private catalogue/IPA manifest metadata; never infer runtime success.

Uses an existing SHA-256 inventory, not another asset hashing pass. Catalogue
header and checksum semantics are undocumented. Checksum equality here compares
recorded strings only, not computed content checksums. Original files are read-only.
"""
import argparse
import collections
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

from preservation_baseline import signature, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if output.is_relative_to(source) or output.is_relative_to(repo):
        parser.error('output must be outside source/repository')
    inventory = [json.loads(x) for x in (output / 'inventory.jsonl').read_text().splitlines()]
    files = {r['path']: r for r in inventory if r.get('type') == 'file'}
    changed = [name for name, row in files.items() if signature((source / name).lstat()) != row['signature']]
    if changed:
        raise ValueError('Source metadata changed since inventory; refresh baseline first')
    cache = source / 'Caches'
    catalogue = (cache / 'asset_list_base.txtCache.txt').read_bytes()
    lines = catalogue[8:].decode('utf-8').splitlines()
    records = {}
    malformed = []
    for i, line in enumerate(lines[1:], 2):
        cols = line.split('\t')
        if len(cols) != 2 or not re.fullmatch('[0-9a-fA-F]{32}', cols[1]):
            malformed.append(i)
        else:
            records[cols[0]] = cols[1]
    manifests = collections.defaultdict(set)
    invalid = []
    manifest_count = 0
    with zipfile.ZipFile(source / 'RealRacing3.ipa') as archive:
        archive_names = set(archive.namelist())
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename).name
            if not (entry.filename.startswith('Payload/') and name.startswith('asset_list_') and name.endswith('.txt')):
                continue
            manifest_count += 1
            if entry.file_size > 16 * 1024 * 1024:
                raise ValueError('Oversized manifest')
            for line in archive.read(entry).decode('utf-8-sig').splitlines():
                if not line:
                    continue
                cols = line.split('\t')
                if len(cols) != 4 or not re.fullmatch('[0-9a-fA-F]{32}', cols[1]) or not all(c.isdigit() for c in cols[2:]):
                    invalid.append({'manifest': entry.filename, 'line': line[:160]})
                    continue
                manifests[cols[0]].add((cols[1], int(cols[2]), int(cols[3])))
    def row_for(path):
        return files.get('Caches/' + path.lstrip('/'))
    catalog_present = [p for p in records if row_for(p)]
    catalog_missing = [p for p in records if not row_for(p)]
    intersection = set(records) & set(manifests)
    matching = [p for p in intersection if records[p] in {r[0] for r in manifests[p]}]
    conflicts = sorted(intersection - set(matching))
    present = [p for p in manifests if row_for(p)]
    missing = [p for p in manifests if not row_for(p)]
    # Columns are interpreted as transfer size and installed size, respectively;
    # validate that interpretation against actual file lengths, not names alone.
    size_matches = [p for p in present if row_for(p)['size'] in {r[2] for r in manifests[p]}]
    size_mismatches = sorted(set(present) - set(size_matches))
    candidates = [r for n, r in files.items() if n.endswith('.bak') and not '/Tracks/' in n]
    updates = []
    for line in (cache / 'asset_list_updates.txt').read_text().splitlines():
        path, checksum, transfer_size, installed_size = line.split('\t')
        local = row_for(path)
        updates.append({'path': path, 'recorded_checksum': checksum,
                        'transfer_size': int(transfer_size), 'installed_size': int(installed_size),
                        'present': local is not None,
                        'size_matches': local is not None and local['size'] == int(installed_size)})
    report = {
        'cache_version_tag': (cache / 'tags/app_version').read_text(),
        'catalogue_header_hex': catalogue[:8].hex(), 'catalogue_first_numeric_line': lines[0],
        'catalogue_records': len(records), 'catalogue_malformed_lines': malformed,
        'catalogue_present': len(catalog_present), 'catalogue_missing': catalog_missing,
        'ipa_manifest_count': manifest_count, 'ipa_unique_paths': len(manifests),
        'ipa_malformed_rows': invalid, 'catalogue_ipa_overlap': len(intersection),
        'catalogue_ipa_recorded_checksum_matches': len(matching),
        'catalogue_ipa_recorded_checksum_conflicts': conflicts,
        'ipa_paths_present_in_cache': len(present), 'ipa_paths_absent_from_cache': missing,
        'ipa_installed_size_matches': len(size_matches), 'ipa_size_mismatches': size_mismatches,
        'absent_path_groups': dict(collections.Counter(p.strip('/').split('/')[0] for p in missing)),
        'absent_paths_found_under_bundle_res': sum('Payload/RealRacing3.app/res/' + p.lstrip('/') in archive_names for p in missing),
        'update_records': updates,
        'ipa_conflicting_path_records': [p for p, rs in manifests.items() if len(rs) > 1],
        'save_backup_candidates': [{'path': r['path'], 'bytes': r['size']} for r in candidates],
        'method_limits': 'Recorded checksum strings compared only; no new asset content hashes. '
                         'Absent optional downloads do not establish damage. Save formats not decoded. '
                         'Undocumented catalogue header/count semantics unknown.',
    }
    write_json(output / 'cache-compatibility.json', report)
    print(json.dumps({k: v for k, v in report.items() if isinstance(v, (str, int)) and k != 'method_limits'}))
    print(json.dumps({k: len(v) for k, v in report.items() if isinstance(v, list)}))


if __name__ == '__main__':
    main()
