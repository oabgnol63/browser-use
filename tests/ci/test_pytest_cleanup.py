from pathlib import Path

from tests.ci.conftest import cleanup_test_artifacts


def test_cleanup_test_artifacts_removes_known_test_dirs(tmp_path: Path) -> None:
	(tmp_path / '.pytest_cache').mkdir()
	(tmp_path / '.runtime').mkdir()
	(tmp_path / '.tmp-test-session').mkdir()
	(tmp_path / 'tmp-test-worker').mkdir()
	(tmp_path / '.tmp-test-artifacts').mkdir()
	(tmp_path / 'keep-me').mkdir()

	cleanup_test_artifacts(tmp_path)

	assert not (tmp_path / '.pytest_cache').exists()
	assert not (tmp_path / '.runtime').exists()
	assert not (tmp_path / '.tmp-test-session').exists()
	assert not (tmp_path / 'tmp-test-worker').exists()
	assert not (tmp_path / '.tmp-test-artifacts').exists()
	assert (tmp_path / 'keep-me').exists()
