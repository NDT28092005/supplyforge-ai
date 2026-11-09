from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from supplyforge.services.model_loader import FailureType, MLServiceError, ModelLoaderService


class ModelRuntimeIntegrityTests(SimpleTestCase):
    def test_checksum_mismatch_rejects_artifact_before_unpickle(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / 'models'
            models.mkdir()
            (models / 'risk.pkl').write_bytes(b'not-the-declared-artifact')

            with self.assertRaises(MLServiceError) as raised:
                ModelLoaderService._validate_manifest_artifacts(root, {
                    'artifact_sha256': {'risk.pkl': '0' * 64},
                })

        self.assertEqual(raised.exception.failure_type, FailureType.MODEL_INCOMPATIBLE)

    @patch('supplyforge.services.model_loader.importlib.metadata.version')
    def test_runtime_version_mismatch_rejects_pickle_runtime(self, package_version):
        package_version.return_value = '9.9.9'

        with self.assertRaises(MLServiceError) as raised:
            ModelLoaderService._validate_runtime_versions({
                'runtime_versions': {'scikit_learn': '1.9.0'},
            })

        self.assertEqual(raised.exception.failure_type, FailureType.MODEL_INCOMPATIBLE)
        self.assertIn('does not match artifact manifest', raised.exception.message)
