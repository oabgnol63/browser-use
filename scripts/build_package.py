from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / 'dist'
SKIP_DIR_NAMES = {
	'.git',
	'.github',
	'.mypy_cache',
	'.pytest_cache',
	'.ruff_cache',
	'.venv',
	'__pycache__',
	'dist',
}
SKIP_FILE_SUFFIXES = {'.pyc', '.pyo'}


def copy_repo_for_build(staging_root: Path) -> None:
	def ignore(_directory: str, names: list[str]) -> set[str]:
		return {
			name
			for name in names
			if name in SKIP_DIR_NAMES or any(name.endswith(suffix) for suffix in SKIP_FILE_SUFFIXES)
		}

	shutil.copytree(REPO_ROOT, staging_root, dirs_exist_ok=True, ignore=ignore)


def copy_dist_back(staging_root: Path) -> None:
	staging_dist = staging_root / 'dist'
	if not staging_dist.exists():
		raise RuntimeError(f'Build completed without a dist directory at {staging_dist}')

	if DIST_DIR.exists():
		shutil.rmtree(DIST_DIR)
	DIST_DIR.mkdir(parents=True, exist_ok=True)

	for artifact in staging_dist.iterdir():
		if artifact.is_file():
			shutil.copy2(artifact, DIST_DIR / artifact.name)


def main(argv: list[str]) -> None:
	with tempfile.TemporaryDirectory(prefix='browser-use-build-') as temp_dir:
		staging_root = Path(temp_dir) / 'repo'
		copy_repo_for_build(staging_root)
		subprocess.run([sys.executable, str(staging_root / 'scripts' / 'embed_external.py')], cwd=staging_root, check=True)
		subprocess.run(['uv', 'build', *argv], cwd=staging_root, check=True)
		copy_dist_back(staging_root)


if __name__ == '__main__':
	main(sys.argv[1:])
