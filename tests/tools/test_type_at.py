import pytest
from browser_use.tools.service import Tools
from browser_use.tools.registry.views import Mode


def test_type_at_registered_in_vision_and_dom():
	tools = Tools(active_mode=Mode.VISION)
	assert 'type_at' in tools.registry.registry.actions
	tools_dom = Tools(active_mode=Mode.DOM)
	assert 'type_at' in tools_dom.registry.registry.actions


def test_type_at_param_model_fields():
	from browser_use.tools.views import TypeAtAction
	a = TypeAtAction(coordinate_x=195, coordinate_y=578, text='Football', submit=True)
	assert a.coordinate_x == 195 and a.text == 'Football' and a.submit is True
	# submit defaults False
	b = TypeAtAction(coordinate_x=1, coordinate_y=2, text='x')
	assert b.submit is False
