"""Offline release-tool checks; run with python -m unittest scripts.test_submission."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts import prepare_submission as release


class SubmissionTests(unittest.TestCase):
    def test_only_curated_sample_files_are_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['samples/selected-works.json', 'samples/README.md',
                         'samples/raw-response.json', 'samples/customer.db', 'samples/original.png']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('sample', encoding='utf-8')
            self.assertEqual(set(release.public_files(root)), {
                'samples/selected-works.json', 'samples/README.md'})

    def test_private_files_are_never_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['README.md', '.env', 'data/store.db', 'tmp/private.txt',
                         'backend/main.py', 'backend/.env', 'backend/secret.pem',
                         'frontend/src/main.tsx', 'frontend/node_modules/a.js']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('safe', encoding='utf-8')
            self.assertEqual(set(release.public_files(root)), {
                'README.md', 'backend/main.py', 'frontend/src/main.tsx'})

    def test_known_secret_is_blocked_without_echoing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            secret = 'private-test-value-934729'
            (root / '.env').write_text('TEXT_API_KEY=' + secret)
            (root / 'README.md').write_text('accidental disclosure: ' + secret)
            with self.assertRaises(ValueError) as error:
                release.scan(root, ['README.md'])
            self.assertNotIn(secret, str(error.exception))

    def test_token_pattern_and_private_key_are_blocked(self):
        for token in ['ghp_' + 'x' * 36, '-----BEGIN ' + 'PRIVATE KEY-----']:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'README.md').write_text(token)
                with self.assertRaises(ValueError):
                    release.scan(root, ['README.md'])

    def test_separate_ima_config_secret_is_also_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env.ima').write_text('IMA_OPENAPI_CLIENTID=private-client-id-example')
            (root / 'README.md').write_text('private-client-id-example')
            with self.assertRaises(ValueError):
                release.scan(root, ['README.md'])

    def test_private_model_endpoint_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            endpoint = 'https://private-model.example.invalid/v1'
            (root / '.env').write_text('TEXT_API_BASE=' + endpoint)
            (root / 'README.md').write_text(endpoint)
            with self.assertRaises(ValueError):
                release.scan(root, ['README.md'])

    def test_cloud_runtime_secret_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private = root / 'data/deployment/modelscope-runtime.json'
            private.parent.mkdir(parents=True)
            private.write_text(json.dumps({'TEXT_API_KEY':'private-cloud-runtime-token'}))
            (root / 'README.md').write_text('private-cloud-runtime-token')
            with self.assertRaises(ValueError):release.scan(root, ['README.md'])

    def test_missing_materials_cannot_be_declared_ready(self):
        result = release.blockers({'team': '比比拉布', 'stage': '初赛'})
        self.assertTrue(any('GitHub' in item for item in result))
        self.assertTrue(any('ima' in item for item in result))
        self.assertTrue(any('入口' in item for item in result))

    def test_no_video_requirement_for_preliminary_stage(self):
        config = {'team': 'x', 'stage': '初赛', 'github_url': 'https://github.com/a/b',
                  'modelscope_url': 'https://modelscope.cn/studios/a/b',
                  'description_url': 'https://github.com/a/b/blob/main/docs/competition/WORK_DESCRIPTION.md',
                  'submission_url': 'https://example.org/form', 'ima_evidence_reviewed': True,
                  'results_reviewed': True, 'public_access_reviewed': True}
        self.assertEqual(release.blockers(config), [])
        config['stage'] = '复赛'
        self.assertTrue(any('视频' in item for item in release.blockers(config)))
        config['video_url'] = 'javascript:alert(1)'
        self.assertTrue(any('视频' in item for item in release.blockers(config)))

    def test_package_hashes_and_html_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'README.md').write_text('# demo', encoding='utf-8')
            out = root / 'output'
            release.build(root, out, {'team': '<script>bad()</script>', 'stage': '初赛'})
            with zipfile.ZipFile(out / 'zhike-source.zip') as archive:
                self.assertEqual(archive.namelist(), ['README.md'])
            manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['files']['README.md']), 64)
            page = (out / 'index.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>bad()', page)
            self.assertIn('待补齐', page)


if __name__ == '__main__':
    unittest.main()
