from pydantic import BaseModel

from browser_use.tools.registry.service import Registry
from browser_use.tools.registry.views import (
	Backend,
	Mode,
	Platform,
	RegisteredAction,
)
from browser_use.tools.service import Tools


class TestBackendEnum:
	def test_backend_values(self):
		assert Backend.CDP == "cdp"
		assert Backend.WEBDRIVER == "webdriver"

	def test_backend_is_str(self):
		assert isinstance(Backend.CDP, str)
		assert isinstance(Backend.WEBDRIVER, str)


class TestModeEnum:
	def test_mode_values(self):
		assert Mode.DOM == "dom"
		assert Mode.VISION == "vision"

	def test_mode_is_str(self):
		assert isinstance(Mode.DOM, str)
		assert isinstance(Mode.VISION, str)


class TestPlatformEnum:
	def test_platform_values(self):
		assert Platform.DESKTOP == "desktop"
		assert Platform.IOS == "ios"
		assert Platform.ANDROID == "android"

	def test_platform_is_str(self):
		assert isinstance(Platform.DESKTOP, str)


class TestRegisteredActionConstraints:
	def test_default_modes_none(self):
		"""No constraint by default — backward compatible."""
		action = RegisteredAction(
			name="test",
			description="test",
			function=lambda: None,
			param_model=BaseModel,
		)
		assert action.modes is None
		assert action.platforms is None

	def test_modes_field(self):
		action = RegisteredAction(
			name="test",
			description="test",
			function=lambda: None,
			param_model=BaseModel,
			modes={Mode.DOM},
		)
		assert action.modes == {Mode.DOM}

	def test_platforms_field(self):
		action = RegisteredAction(
			name="test",
			description="test",
			function=lambda: None,
			param_model=BaseModel,
			platforms={Platform.IOS, Platform.ANDROID},
		)
		assert action.platforms == {Platform.IOS, Platform.ANDROID}

	def test_backends_field(self):
		action = RegisteredAction(
			name="test",
			description="test",
			function=lambda: None,
			param_model=BaseModel,
			backends={Backend.CDP},
		)
		assert action.backends == {Backend.CDP}

	def test_default_backends_none(self):
		action = RegisteredAction(
			name="test",
			description="test",
			function=lambda: None,
			param_model=BaseModel,
		)
		assert action.backends is None


class TestRegistryDecorator:
	def test_action_accepts_modes_kwarg(self):
		"""Decorator should accept modes and pass to RegisteredAction."""
		registry = Registry()

		@registry.action("DOM-only tool", modes={Mode.DOM})
		async def dom_tool():
			pass

		assert registry.registry.actions["dom_tool"].modes == {Mode.DOM}

	def test_action_accepts_platforms_kwarg(self):
		registry = Registry()

		@registry.action("Mobile tool", platforms={Platform.IOS, Platform.ANDROID})
		async def mobile_tool():
			pass

		assert registry.registry.actions["mobile_tool"].platforms == {Platform.IOS, Platform.ANDROID}

	def test_action_no_constraints_by_default(self):
		registry = Registry()

		@registry.action("Universal tool")
		async def universal_tool():
			pass

		assert registry.registry.actions["universal_tool"].modes is None
		assert registry.registry.actions["universal_tool"].platforms is None
		assert registry.registry.actions["universal_tool"].backends is None

	def test_action_accepts_backends_kwarg(self):
		registry = Registry()

		@registry.action("CDP-only tool", backends={Backend.CDP})
		async def cdp_tool():
			pass

		assert registry.registry.actions["cdp_tool"].backends == {Backend.CDP}


class TestRegistrationTimeFiltering:
	def test_vision_mode_excludes_dom_only_tools(self):
		"""DOM-only tools should be skipped in vision-only mode."""
		registry = Registry()
		registry.active_mode = Mode.VISION

		@registry.action("DOM-only tool", modes={Mode.DOM})
		async def dom_tool():
			pass

		assert "dom_tool" not in registry.registry.actions

	def test_vision_mode_allows_vision_tools(self):
		registry = Registry()
		registry.active_mode = Mode.VISION

		@registry.action("Vision tool", modes={Mode.VISION})
		async def vision_tool():
			pass

		assert "vision_tool" in registry.registry.actions

	def test_vision_mode_allows_unconstrained_tools(self):
		"""Actions with modes=None should always be registered."""
		registry = Registry()
		registry.active_mode = Mode.VISION

		@registry.action("Universal tool")
		async def universal_tool():
			pass

		assert "universal_tool" in registry.registry.actions

	def test_dom_mode_allows_dom_tools(self):
		"""DOM mode includes DOM tools."""
		registry = Registry()
		registry.active_mode = Mode.DOM

		@registry.action("DOM tool", modes={Mode.DOM})
		async def dom_tool():
			pass

		assert "dom_tool" in registry.registry.actions

	def test_dom_mode_allows_vision_tools(self):
		"""DOM mode is a superset — it includes vision tools too."""
		registry = Registry()
		registry.active_mode = Mode.DOM

		@registry.action("Vision tool", modes={Mode.VISION})
		async def vision_tool():
			pass

		assert "vision_tool" in registry.registry.actions

	def test_dom_mode_allows_both_modes_tools(self):
		registry = Registry()
		registry.active_mode = Mode.DOM

		@registry.action("Both modes", modes={Mode.DOM, Mode.VISION})
		async def both_tool():
			pass

		assert "both_tool" in registry.registry.actions

	def test_active_platform_filters_at_registration(self):
		registry = Registry()
		registry.active_platform = Platform.DESKTOP

		@registry.action("Mobile tool", platforms={Platform.IOS, Platform.ANDROID})
		async def mobile_tool():
			pass

		assert "mobile_tool" not in registry.registry.actions

	def test_active_platform_allows_matching_action(self):
		registry = Registry()
		registry.active_platform = Platform.IOS

		@registry.action("Mobile tool", platforms={Platform.IOS, Platform.ANDROID})
		async def mobile_tool():
			pass

		assert "mobile_tool" in registry.registry.actions

	def test_both_filters_must_pass(self):
		"""Both mode AND platform must match for registration."""
		registry = Registry()
		registry.active_mode = Mode.DOM
		registry.active_platform = Platform.DESKTOP

		@registry.action("DOM mobile tool", modes={Mode.DOM}, platforms={Platform.IOS})
		async def dom_mobile():
			pass

		# Mode matches (DOM) but platform doesn't (DESKTOP not in {IOS})
		assert "dom_mobile" not in registry.registry.actions

	def test_no_active_filters_registers_everything(self):
		"""When active_mode/active_platform/active_backend are None, all actions register."""
		registry = Registry()

		@registry.action(
			"Constrained tool",
			modes={Mode.DOM},
			platforms={Platform.DESKTOP},
			backends={Backend.CDP},
		)
		async def constrained():
			pass

		assert "constrained" in registry.registry.actions

	def test_active_backend_filters_at_registration(self):
		registry = Registry()
		registry.active_backend = Backend.WEBDRIVER

		@registry.action("CDP-only tool", backends={Backend.CDP})
		async def cdp_tool():
			pass

		assert "cdp_tool" not in registry.registry.actions

	def test_active_backend_allows_matching_action(self):
		registry = Registry()
		registry.active_backend = Backend.CDP

		@registry.action("CDP-only tool", backends={Backend.CDP})
		async def cdp_tool():
			pass

		assert "cdp_tool" in registry.registry.actions

	def test_active_backend_allows_unconstrained_tool(self):
		registry = Registry()
		registry.active_backend = Backend.WEBDRIVER

		@registry.action("Backend-agnostic tool")
		async def universal_tool():
			pass

		assert "universal_tool" in registry.registry.actions


class TestBuiltinCdpBackendAnnotations:
	def test_cdp_only_tools_have_backend_constraint(self):
		tools = Tools()
		cdp_only = [
			"evaluate", "save_as_pdf", "search_page", "find_elements", "press_and_hold_coordinate",
		]
		for name in cdp_only:
			action = tools.registry.registry.actions.get(name)
			assert action is not None, f"Tool '{name}' not found in registry"
			assert action.backends == {Backend.CDP}, (
				f"Tool '{name}' should be backends={{Backend.CDP}}, got {action.backends}"
			)

	def test_backend_agnostic_tools_have_no_backend_constraint(self):
		tools = Tools()
		unconstrained = [
			"done", "wait", "go_back", "go_forward", "search", "navigate",
			"switch", "close", "send_keys", "write_file", "replace_file",
			"read_file", "screenshot", "scroll", "input",
			"scroll_coordinate", "hover_coordinate", "drag_and_drop_coordinate",
		]
		for name in unconstrained:
			action = tools.registry.registry.actions.get(name)
			assert action is not None, f"Tool '{name}' not found in registry"
			assert action.backends is None, (
				f"Tool '{name}' should be backends=None, got {action.backends}"
			)

	def test_multiple_click_coordinate_declares_supported_backends(self):
		tools = Tools()
		action = tools.registry.registry.actions.get("multiple_click_coordinate")
		assert action is not None
		assert action.backends == {Backend.CDP, Backend.WEBDRIVER}


class TestBuiltinToolAnnotations:
	def test_dom_only_tools_have_mode_constraint(self):
		"""DOM-dependent tools should declare modes={Mode.DOM}."""
		tools = Tools()
		dom_only_tools = [
			"input", "search_page", "find_elements",
			"find_text", "select_dropdown", "dropdown_options",
			"extract", "upload_file",
		]
		for name in dom_only_tools:
			action = tools.registry.registry.actions.get(name)
			assert action is not None, f"Tool '{name}' not found in registry"
			assert action.modes == {Mode.DOM}, f"Tool '{name}' should be modes={{Mode.DOM}}, got {action.modes}"

	def test_unconstrained_tools_have_no_mode(self):
		"""Mode-agnostic tools should have modes=None."""
		tools = Tools()
		unconstrained_tools = [
			"done", "wait", "go_back", "go_forward", "search",
			"navigate", "switch", "close", "evaluate", "send_keys",
			"write_file", "replace_file", "read_file",
			"screenshot", "save_as_pdf", "scroll",
		]
		for name in unconstrained_tools:
			action = tools.registry.registry.actions.get(name)
			assert action is not None, f"Tool '{name}' not found in registry"
			assert action.modes is None, f"Tool '{name}' should be modes=None, got {action.modes}"

	def test_explicit_cross_mode_coordinate_tools(self):
		"""New coordinate tools should declare DOM+VISION explicitly."""
		tools = Tools()
		for name in ["multiple_click_coordinate", "press_and_hold_coordinate"]:
			action = tools.registry.registry.actions.get(name)
			assert action is not None, f"Tool '{name}' not found in registry"
			assert action.modes == {Mode.DOM, Mode.VISION}, (
				f"Tool '{name}' should be modes={{Mode.DOM, Mode.VISION}}, got {action.modes}"
			)


class TestCoordinateClickingModesPropagation:
	def test_index_click_has_dom_mode(self):
		"""Index-only click requires DOM, so modes={Mode.DOM}."""
		tools = Tools()
		tools.set_coordinate_clicking(False)
		action = tools.registry.registry.actions["click"]
		assert action.modes == {Mode.DOM}

	def test_coordinate_click_has_no_mode_constraint(self):
		"""Coordinate-capable click works without DOM, so modes=None."""
		tools = Tools()
		tools.set_coordinate_clicking(True)
		action = tools.registry.registry.actions["click"]
		assert action.modes is None

	def test_index_hover_has_dom_mode(self):
		tools = Tools()
		tools.set_coordinate_clicking(False)
		action = tools.registry.registry.actions["hover"]
		assert action.modes == {Mode.DOM}

	def test_coordinate_hover_has_no_mode_constraint(self):
		tools = Tools()
		tools.set_coordinate_clicking(True)
		action = tools.registry.registry.actions["hover"]
		assert action.modes is None


class TestSwipeCoordinateMigration:
	def test_swipe_registered_by_default(self):
		"""swipe_coordinate should be in the registry with platform constraint."""
		tools = Tools()
		action = tools.registry.registry.actions.get("swipe_coordinate")
		assert action is not None
		assert action.platforms == {Platform.IOS, Platform.ANDROID}


class TestToolsInitWithConstraints:
	def test_tools_accepts_active_mode(self):
		"""Tools should accept active_mode and set it on the registry."""
		tools = Tools(active_mode=Mode.VISION)
		assert tools.registry.active_mode == Mode.VISION

	def test_tools_accepts_active_platform(self):
		tools = Tools(active_platform=Platform.ANDROID)
		assert tools.registry.active_platform == Platform.ANDROID

	def test_vision_mode_filters_dom_tools(self):
		"""DOM-only tools should not be registered when active_mode=VISION."""
		tools = Tools(active_mode=Mode.VISION)
		assert "input" not in tools.registry.registry.actions
		assert "extract" not in tools.registry.registry.actions
		assert "scroll" in tools.registry.registry.actions  # scroll works without DOM index
		# Universal tools still present
		assert "done" in tools.registry.registry.actions
		assert "wait" in tools.registry.registry.actions
		assert "navigate" in tools.registry.registry.actions
		assert "send_keys" in tools.registry.registry.actions

	def test_desktop_platform_filters_mobile_tools(self):
		"""Mobile-only tools should not register on desktop."""
		tools = Tools(active_platform=Platform.DESKTOP)
		assert "swipe_coordinate" not in tools.registry.registry.actions
		assert "done" in tools.registry.registry.actions

	def test_mobile_platform_keeps_swipe(self):
		tools = Tools(active_platform=Platform.IOS)
		assert "swipe_coordinate" in tools.registry.registry.actions

	def test_android_platform_keeps_swipe(self):
		tools = Tools(active_platform=Platform.ANDROID)
		assert "swipe_coordinate" in tools.registry.registry.actions

	def test_defaults_register_everything(self):
		"""No active constraints = all tools registered (backward compatible)."""
		tools = Tools()
		assert "input" in tools.registry.registry.actions
		assert "swipe_coordinate" in tools.registry.registry.actions

	def test_tools_accepts_active_backend(self):
		tools = Tools(active_backend=Backend.WEBDRIVER)
		assert tools.registry.active_backend == Backend.WEBDRIVER

	def test_webdriver_backend_filters_cdp_only_tools(self):
		"""CDP-only tools should not register when active_backend=WEBDRIVER."""
		tools = Tools(active_backend=Backend.WEBDRIVER)
		# Tools that hit cdp_client.send.* directly
		assert "evaluate" not in tools.registry.registry.actions
		assert "save_as_pdf" not in tools.registry.registry.actions
		assert "search_page" not in tools.registry.registry.actions
		assert "find_elements" not in tools.registry.registry.actions
		# Backend-agnostic tools still present
		assert "click" in tools.registry.registry.actions
		assert "input" in tools.registry.registry.actions
		assert "navigate" in tools.registry.registry.actions
		assert "scroll" in tools.registry.registry.actions
		assert "send_keys" in tools.registry.registry.actions
		# Coordinate tools are backend-agnostic — Selenium has handlers
		assert "scroll_coordinate" in tools.registry.registry.actions
		assert "hover_coordinate" in tools.registry.registry.actions
		assert "drag_and_drop_coordinate" in tools.registry.registry.actions

	def test_cdp_backend_keeps_cdp_tools(self):
		tools = Tools(active_backend=Backend.CDP)
		assert "evaluate" in tools.registry.registry.actions
		assert "save_as_pdf" in tools.registry.registry.actions
		assert "search_page" in tools.registry.registry.actions
		assert "find_elements" in tools.registry.registry.actions
