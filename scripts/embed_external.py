from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


class AssetEmbedder:
	def __init__(self, target_path: Path, start_marker: str, end_marker: str):
		self.target_path = target_path
		self.start_marker = start_marker
		self.end_marker = end_marker
		self.pattern = re.compile(
			re.escape(start_marker) + r'\n.*?\n' + re.escape(end_marker),
			re.DOTALL,
		)

	def _render_block(self, content: str) -> str:
		return f'{self.start_marker}\n{content}\n{self.end_marker}'

	def embed(self, content_lines: list[str]) -> bool:
		module_text = self.target_path.read_text(encoding='utf-8')
		if not self.pattern.search(module_text):
			raise RuntimeError(f'Could not find generated block in {self.target_path}')

		new_block = self._render_block('\n'.join(content_lines))
		updated_text = self.pattern.sub(lambda _: new_block, module_text, count=1)

		if updated_text != module_text:
			self.target_path.write_text(updated_text, encoding='utf-8')
			return True
		return False


class PromptEmbedder(AssetEmbedder):
	def __init__(self):
		target = REPO_ROOT / 'browser_use' / 'agent' / 'prompts.py'
		super().__init__(
			target,
			'# BEGIN GENERATED PROMPT TEMPLATES',
			'# END GENERATED PROMPT TEMPLATES',
		)
		self.source_dir = target.with_name('system_prompts')

	def read_templates(self) -> dict[str, str]:
		return {
			path.name: path.read_text(encoding='utf-8')
			for path in sorted(self.source_dir.glob('*.md'))
		}

	def run(self) -> bool:
		templates = self.read_templates()
		lines = ['PROMPT_TEMPLATES = {']
		lines.extend(f'\t{name!r}: {text!r},' for name, text in templates.items())
		lines.append('}')
		return self.embed(lines)


class JSEmbedder(AssetEmbedder):
	def __init__(self):
		target = REPO_ROOT / 'browser_use' / 'selenium' / 'dom_service.py'
		super().__init__(
			target,
			'# BEGIN GENERATED DOM TREE JS',
			'# END GENERATED DOM TREE JS',
		)
		self.source_file = target.parents[1] / 'dom' / 'dom_tree_js' / 'index.js'

	def run(self) -> bool:
		js_content = self.source_file.read_text(encoding='utf-8')
		lines = [f'INDEX_JS = {js_content!r}']
		return self.embed(lines)


def main():
	embedders = [PromptEmbedder(), JSEmbedder()]

	for embedder in embedders:
		name = embedder.__class__.__name__
		try:
			if embedder.run():
				print(f'[OK] {name}: Updated {embedder.target_path.name}')
			else:
				print(f'[INFO] {name}: Already up to date')
		except Exception as e:
			print(f'[ERROR] {name}: Failed to update {embedder.target_path.name}: {e}')


if __name__ == '__main__':
	main()
