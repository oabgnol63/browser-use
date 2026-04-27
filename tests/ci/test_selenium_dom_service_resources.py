from browser_use.selenium.dom_service import _load_dom_tree_js


def test_load_dom_tree_js_reads_packaged_dom_tree_resource():
	js_code = _load_dom_tree_js()

	assert 'DOM Tree Extraction Script for Browser-Use' in js_code
	assert 'compactMode' in js_code
