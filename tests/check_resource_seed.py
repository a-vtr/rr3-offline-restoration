"""Meaningful host scratch tests; never implies iOS initialization succeeds."""
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prototype_resource_seed import restore


def main():
    with tempfile.TemporaryDirectory(prefix='rr3-seed-test-') as tmp:
        root = Path(tmp)
        seed, container = root / 'seed', root / 'container'
        seed.mkdir(); container.mkdir()
        (container / '.rr3-seed-lab').write_text('host-prototype-only\n')
        (container / 'Documents').mkdir()
        progress = container / 'Documents/progress.dat'
        progress.write_bytes(b'existing progress')
        payload = b'original compressed bytes unchanged'
        p = seed / 'Tracks/Test/high/file.z'
        p.parent.mkdir(parents=True); p.write_bytes(payload)
        row = {'path': 'Tracks/Test/high/file.z', 'bytes': len(payload),
               'sha256': hashlib.sha256(payload).hexdigest()}
        assert restore(seed, container, [row])['copied'] == 1
        assert restore(seed, container, [row])['retained'] == 1
        target = container / 'Library/Caches' / row['path']
        target.unlink()  # Simulated purge of synthetic test resource only.
        assert restore(seed, container, [row])['copied'] == 1
        target.write_bytes(b'corrupt')
        assert restore(seed, container, [row])['copied'] == 1
        assert target.read_bytes() == payload
        p.write_bytes(b'bad seed')
        try:
            restore(seed, container, [row])
            raise AssertionError('Invalid seed accepted')
        except ValueError:
            pass
        assert target.read_bytes() == payload
        for unsafe in ['../Documents/progress.dat', 'Documents/progress.dat',
                       '/Tracks/a', 'Tracks//a', 'UDSF.2.dat', 'Tracks/a.bak']:
            try:
                restore(seed, container, [{**row, 'path': unsafe}])
                raise AssertionError('Unsafe/state path accepted')
            except ValueError:
                pass
        (container / 'Library/Caches/vehicles').symlink_to(container / 'Documents')
        try:
            restore(seed, container, [{**row, 'path': 'vehicles/progress.dat'}])
            raise AssertionError('Symlink accepted')
        except ValueError:
            pass
        assert progress.read_bytes() == b'existing progress'
    print('Host prototype: initial copy, no-op, purge repair, corruption repair, bad-seed rejection, state/path/symlink protection passed.')


if __name__ == '__main__':
    main()
