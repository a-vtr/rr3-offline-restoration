"""Exercise the guard against real temporary Git indexes; never touch project index."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts/check_publication.py'


class PublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        # Synthetic test identity; never used for an actual project commit.
        self.git('config', 'user.email', '12345+fixture@users.noreply.github.com')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, env=self.env,
                              capture_output=True, check=True)

    def stage(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        self.git('add', '-f', '--', name)

    def check(self, success, category=''):
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        self.assertIn(category, result.stderr)
        return result

    def test_original_text_passes(self):
        self.stage('docs/method.md', b'Original methodology\n')
        self.check(True)

    def test_force_added_game_path_fails(self):
        self.stage('Caches/vehicles/example.txt', b'proprietary')
        self.check(False, 'private/proprietary path')

    def test_force_added_operational_notes_fail(self):
        self.stage('docs/SESSION_STATE.md', b'Local operational history')
        self.check(False, 'private/proprietary path')

    def test_index_is_checked_instead_of_worktree(self):
        secret = b'ghp_' + b'A' * 30
        self.stage('notes.txt', secret)
        (self.root / 'notes.txt').write_text('clean unstaged replacement')
        result = self.check(False, 'credential/key')
        self.assertNotIn(secret.decode(), result.stderr)

    def test_private_email_is_redacted(self):
        value = b'fixture' + b'@' + b'example.test'
        self.stage('notes.txt', value)
        result = self.check(False, 'email address')
        self.assertNotIn(value.decode(), result.stderr)

    def test_private_identity_fails(self):
        self.git('config', 'user.email', 'fixture' + '@' + 'example.test')
        self.check(False, 'owner-verified')

    def test_blank_identity_fails(self):
        self.git('config', 'user.email', '')
        self.check(False, 'owner-verified')

    def test_local_path_is_redacted(self):
        value = b'/' + b'Users/' + b'private-owner/input'
        self.stage('notes.txt', value)
        result = self.check(False, 'filesystem path')
        self.assertNotIn(value.decode(), result.stderr)

    def test_worktree_checks_unstaged_file(self):
        (self.root / 'notes.txt').write_bytes(b'ghp_' + b'B' * 30)
        result = subprocess.run([sys.executable, str(SCRIPT), '--worktree'],
                                cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('credential/key', result.stderr)
        self.assertEqual(self.git('ls-files').stdout, b'')

    def test_binary_fails(self):
        self.stage('renamed.txt', b'asset\x00content')
        self.check(False, 'binary content')

    def test_symlink_fails(self):
        (self.root / 'link').symlink_to('/nonexistent-private-data')
        self.git('add', 'link')
        self.check(False, 'symlink')

    def test_large_file_fails(self):
        self.stage('large.txt', b'x' * (2 * 1024 * 1024 + 1))
        self.check(False, 'review limit')


if __name__ == '__main__':
    unittest.main()
