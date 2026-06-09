import json
from unittest.mock import MagicMock

from browser_use.selenium.dom_service import SeleniumDomService, _load_dom_tree_js


def test_load_dom_tree_js_reads_packaged_dom_tree_resource(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_DEV_ENV', '1')
	js_code = _load_dom_tree_js()

	assert 'DOM Tree Extraction Script for Browser-Use' in js_code
	assert 'compactMode' in js_code


def test_dom_service_uses_json_transport_for_ios_appium():
	driver = MagicMock()
	driver.capabilities = {
		'platformName': 'iOS',
		'appium:automationName': 'XCUITest',
	}
	driver.execute_script.return_value = json.dumps({'map': {'1': {'children': []}}, 'rootId': 1})

	service = SeleniumDomService(driver)
	service.js_code = '(function(args){ return { map: {"1": {children: []}}, rootId: 1, iframeNodes: [] }; })'

	result = service._execute_dom_extraction_script({'compactMode': True})

	assert result == {'map': {'1': {'children': []}}, 'rootId': 1}
	driver.execute_script.assert_called_once()
	assert 'JSON.stringify' in driver.execute_script.call_args.args[0]


def test_dom_service_falls_back_to_json_transport_after_recursive_transfer_error():
	driver = MagicMock()
	driver.capabilities = {'platformName': 'macOS'}
	driver.execute_script.side_effect = [
		Exception('Recursive object cannot be transferred'),
		json.dumps({'map': {'1': {'children': []}}, 'rootId': 1}),
	]

	service = SeleniumDomService(driver)
	service.js_code = '(function(args){ return { map: {"1": {children: []}}, rootId: 1, iframeNodes: [] }; })'

	result = service._execute_dom_extraction_script({'compactMode': True})

	assert result == {'map': {'1': {'children': []}}, 'rootId': 1}
	assert driver.execute_script.call_count == 2
	assert 'JSON.stringify' in driver.execute_script.call_args_list[1].args[0]
