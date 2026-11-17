"""Host-only resource-copy prototype; not an iOS bootstrap or full asset importer.

Requires an explicitly marked scratch container. Only reviewed gameplay roots and
catalogue metadata can be restored. Never runs RR3 or edits an IPA.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

RESOURCE_ROOTS = {'Tracks', 'vehicles', 'gui_assets'}
METADATA = {'asset_list_base.txtCache.txt', 'asset_list_updates.txt',
            'asset_list_updates.info', 'tags/app_version'}


def checked_path(root, relative):
    p = PurePosixPath(relative)
    if (not relative or p.is_absolute() or '..' in p.parts or '\\' in relative
            or str(p) != relative or '\0' in relative):
        raise ValueError('Unsafe or noncanonical resource path')
    if p.parts[0] not in RESOURCE_ROOTS and relative not in METADATA:
        raise ValueError('Not a reviewed gameplay resource/metadata path')
    if p.name.endswith('.bak'):
        raise ValueError('Save backups are not resources')
    current = root
    if root.is_symlink():
        raise ValueError('Symlink root')
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlink in resource path')
    return current


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def restore(seed, container, manifest):
    if Path(seed).is_symlink() or Path(container).is_symlink():
        raise ValueError('Symlink root')
    seed, container = Path(seed).resolve(), Path(container).resolve()
    marker = container / '.rr3-seed-lab'
    if not marker.is_file() or marker.is_symlink() or marker.read_text() != 'host-prototype-only\n':
        raise ValueError('Requires marked scratch container, not a live application')
    if seed.is_relative_to(container) or container.is_relative_to(seed):
        raise ValueError('Seed/container overlap')
    runtime = container / 'Library' / 'Caches'
    if (container / 'Library').is_symlink() or runtime.is_symlink():
        raise ValueError('Symlink runtime root')
    seen = set()
    operations = []
    # Validate every entry/path before any write.
    for row in manifest:
        name, size, expected = row['path'], row['bytes'], row['sha256']
        if name in seen or not isinstance(size, int) or size < 0 or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid manifest entry')
        seen.add(name)
        source, target = checked_path(seed, name), checked_path(runtime, name)
        operations.append((source, target, size, expected))
    copied, retained = 0, 0
    for source, target, size, expected in operations:
        if not source.is_file() or source.stat().st_size != size or digest(source) != expected:
            raise ValueError('Seed integrity failure')
        if target.is_file() and target.stat().st_size == size and digest(target) == expected:
            retained += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        scratch = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.rr3-seed-', delete=False) as f:
                scratch = Path(f.name)
                with source.open('rb') as src:
                    for block in iter(lambda: src.read(1024 * 1024), b''):
                        f.write(block)
                f.flush()
                os.fsync(f.fileno())
            if scratch.stat().st_size != size or digest(scratch) != expected:
                raise ValueError('Copied resource integrity failure')
            os.replace(scratch, target)
            copied += 1
        finally:
            if scratch is not None and scratch.exists():
                scratch.unlink()
    return {'copied': copied, 'retained': retained, 'scope': 'host scratch only'}
