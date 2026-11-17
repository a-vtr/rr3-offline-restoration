"""Synthetic macOS metadata/safety checks. Never accesses preserved game data."""
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from create_master_backup import DarwinMetadata, tree


def main():
    native = DarwinMetadata()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.mkdir()
        file = source / 'fixture'
        file.write_bytes(b'preservation fixture')
        before = file.lstat()
        assert native.read(file, before)['acl'] == ''
        subprocess.run(['/bin/chmod', '+a', 'everyone allow read', str(file)], check=True)
        assert 'allow' in native.read(file, file.lstat())['acl']
        # Set an extended attribute only on a disposable synthetic fixture.
        native.lib.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        assert native.lib.setxattr(bytes(file), b'org.example.fixture', b'fixture', 7, 0, 0) == 0
        metadata = native.read(file, file.lstat())
        assert metadata['xattrs']['org.example.fixture']['bytes'] == 7
        files, dirs = tree(source)
        assert set(files) == {'fixture'} and set(dirs) == {'.'}
        (source / 'link').symlink_to(file)
        try:
            tree(source)
        except ValueError:
            pass
        else:
            raise AssertionError('Unsafe tree accepted')
        # Existing destination must be rejected before any report/copy is created.
        script = Path(__file__).resolve().parents[1] / 'scripts/create_master_backup.py'
        target = root / 'existing'
        target.mkdir()
        marker = target / 'marker'
        marker.write_bytes(b'keep')
        reports = root / 'reports'
        result = subprocess.run([sys.executable, str(script), str(source), str(root / 'baseline'),
                                 str(root), str(target), str(reports), str(root)], capture_output=True)
        assert result.returncode != 0 and marker.read_bytes() == b'keep' and not reports.exists()
    print('PASS: absent/present ACLs, xattr reading, exact tree enumeration, symlink rejection, existing-target refusal')


if __name__ == '__main__':
    main()
