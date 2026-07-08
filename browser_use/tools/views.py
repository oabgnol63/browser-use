from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


# Action Input Models
class ExtractAction(BaseModel):
	query: str
	extract_links: bool = Field(
		default=False, description='Set True to true if the query requires links, else false to safe tokens'
	)
	extract_images: bool = Field(
		default=False,
		description='Set True to include image src URLs in extracted markdown. Auto-enabled when query contains image-related keywords.',
	)
	start_from_char: int = Field(
		default=0, description='Use this for long markdowns to start from a specific character (not index in browser_state)'
	)
	output_schema: SkipJsonSchema[dict | None] = Field(
		default=None,
		description='Optional JSON Schema dict. When provided, extraction returns validated JSON matching this schema instead of free-text.',
	)
	already_collected: list[str] = Field(
		default_factory=list,
		description='Item identifiers (name, URL, or ID) already collected in prior extract calls on other pages. The extractor will skip items matching these to prevent duplicates. Use when paginating across multiple pages.',
	)


class SearchPageAction(BaseModel):
	pattern: str = Field(description='Text or regex pattern to search for in page content')
	regex: bool = Field(default=False, description='Treat pattern as regex (default: literal text match)')
	case_sensitive: bool = Field(default=False, description='Case-sensitive search (default: case-insensitive)')
	context_chars: int = Field(default=150, description='Characters of surrounding context per match')
	css_scope: str | None = Field(default=None, description='CSS selector to limit search scope (e.g. "div#main")')
	max_results: int = Field(default=25, description='Maximum matches to return')


class FindElementsAction(BaseModel):
	selector: str = Field(description='CSS selector to query elements (e.g. "table tr", "a.link", "div.product")')
	attributes: list[str] | None = Field(
		default=None,
		description='Specific attributes to extract (e.g. ["href", "src", "class"]). If not set, returns tag and text only.',
	)
	max_results: int = Field(default=50, description='Maximum elements to return')
	include_text: bool = Field(default=True, description='Include text content of each element')


class SearchAction(BaseModel):
	query: str
	engine: str = Field(
		default='duckduckgo', description='duckduckgo, google, bing (use duckduckgo by default because less captchas)'
	)


# Backward compatibility alias
SearchAction = SearchAction


class NavigateAction(BaseModel):
	url: str
	new_tab: bool = Field(default=False)


# Backward compatibility alias
GoToUrlAction = NavigateAction


class ClickCacheRegion(BaseModel):
	x: int = Field(ge=0, description='Left edge of the reusable visual click context rectangle')
	y: int = Field(ge=0, description='Top edge of the reusable visual click context rectangle')
	width: int = Field(ge=1, description='Width of the reusable visual click context rectangle')
	height: int = Field(ge=1, description='Height of the reusable visual click context rectangle')


class ClickElementAction(BaseModel):
	index: int | None = Field(default=None, ge=1, description='Element index from browser_state')
	coordinate_x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')
	target_description: str | None = Field(
		default=None,
		description='Concise visual description of the intended click target for later verification or relocation',
	)
	cache_region: ClickCacheRegion | None = Field(
		default=None,
		description=(
			'Reusable stable visual container coordinates for screenshot cache matching. '
			'For a button inside a modal, banner, prompt, or overlay, use the outer visible '
			'modal/container rectangle, not a tight box around the button.'
		),
	)
	# expect_download: bool = Field(default=False, description='set True if expecting a download, False otherwise')  # moved to downloads_watchdog.py
	# click_count: int = 1  # TODO


class ClickElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='ClickElementAction')

	index: int = Field(ge=1, description='Element index from browser_state')


class HoverElementAction(BaseModel):
	index: int | None = Field(default=None, ge=1, description='Element index from browser_state')
	coordinate_x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')


class HoverElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='HoverElementAction')

	index: int = Field(ge=1, description='Element index from browser_state')


class InputTextAction(BaseModel):
	index: int = Field(ge=0, description='from browser_state')
	text: str = Field(description='Text to enter. With clear=True, text="" clears the field without typing.')
	clear: bool = Field(default=True, description='Clear existing text before typing. Set to False to append instead.')


class DoneAction(BaseModel):
	text: str = Field(
		description=(
			'Final message to the user. '
			'ONLY report data you directly observed in browser_state, tool outputs, or screenshots during this session. '
			'Do NOT use training knowledge to fill gaps — if information was not found on the page, say so explicitly. '
			'Do NOT claim completion of steps from compacted_memory or prior session summaries '
			'unless you explicitly verified them yourself. '
			'If uncertain whether a prior step completed, say so explicitly.'
		)
	)
	success: bool = Field(default=True, description='True if user_request completed successfully')
	files_to_display: list[str] | None = Field(default=[])


T = TypeVar('T', bound=BaseModel)


def _hide_internal_fields_from_schema(schema: dict) -> None:
	"""Remove internal fields from the JSON schema to avoid collisions with user models."""
	props = schema.get('properties', {})
	props.pop('success', None)
	props.pop('files_to_display', None)


class StructuredOutputAction(BaseModel, Generic[T]):
	model_config = ConfigDict(json_schema_extra=_hide_internal_fields_from_schema)

	success: bool = Field(default=True, description='True if user_request completed successfully')
	data: T = Field(description='The actual output data matching the requested schema')
	files_to_display: list[str] | None = Field(default=[])


class SwitchTabAction(BaseModel):
	tab_id: str = Field(min_length=4, max_length=4, description='4-char id')


class CloseTabAction(BaseModel):
	tab_id: str = Field(min_length=4, max_length=4, description='4-char id')


class ScrollAction(BaseModel):
	down: bool = Field(default=True, description='down=True=scroll down, down=False scroll up')
	pages: float = Field(default=1.0, description='0.5=half page, 1=full page, 10=to bottom/top')
	index: int | None = Field(
		default=None,
		description='Optional element index to scroll within specific container. Leave empty to scroll the main page.',
	)


class HoverCoordinateAction(BaseModel):
	coordinate_x: int = Field(description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int = Field(description='Vertical coordinate relative to viewport top edge')


class DragAndDropElementAction(BaseModel):
	"""Hybrid: provide either index OR (x, y) for each endpoint. Index takes priority."""

	start_index: int | None = Field(default=None, ge=1, description='Element index for drag start (preferred when available)')
	start_x: int | None = Field(default=None, description='Start horizontal coordinate relative to viewport left edge')
	start_y: int | None = Field(default=None, description='Start vertical coordinate relative to viewport top edge')
	end_index: int | None = Field(default=None, ge=1, description='Element index for drag end (preferred when available)')
	end_x: int | None = Field(default=None, description='End horizontal coordinate relative to viewport left edge')
	end_y: int | None = Field(default=None, description='End vertical coordinate relative to viewport top edge')


class DragAndDropElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='DragAndDropElementAction')

	start_index: int = Field(ge=1, description='Element index for drag start')
	end_index: int = Field(ge=1, description='Element index for drag end')


class ClickTarget(BaseModel):
	"""A single click target — either an element index OR an (x, y) coordinate."""

	index: int | None = Field(default=None, ge=1, description='Element index (preferred when available)')
	x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')


class MultipleClickElementAction(BaseModel):
	"""List of click targets. Each item is either {index: N} or {x: X, y: Y}."""

	points: list[ClickTarget] = Field(
		description=(
			'List of click targets in sequence. Each item is either {"index": N} or {"x": X, "y": Y}. '
			'Prefer index when an interactive element covers the target. Use coordinates for empty space '
			'or captcha tiles where no DOM element exists.'
		)
	)


class MultipleClickElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='MultipleClickElementAction')

	indices: list[int] = Field(description='List of element indices to click in sequence')


class VisionClickLoopAction(BaseModel):
	"""Run a bounded screenshot-guided coordinate click loop for dynamic visual flows."""

	instruction: str = Field(
		description='Visual instruction for the loop, e.g. "click all images matching motorcycle".'
	)
	max_rounds: int = Field(default=5, ge=1, le=10, description='Maximum number of LLM decision rounds.')
	llm_timeout_seconds: float = Field(
		default=90.0,
		ge=5.0,
		le=300.0,
		description='Timeout for each internal LLM decision call.',
	)
	screenshot_detail: Literal['auto', 'low', 'high'] = Field(
		default='auto',
		description='Vision detail hint passed to the internal screenshot message.',
	)
	click_finish_when_ready: bool = Field(
		default=True,
		description='If true, the loop should click the final Submit/Verify/Next control itself once the image-selection task is complete.',
	)
	inter_click_delay_seconds: float = Field(
		default=0.08,
		ge=0.0,
		le=2.0,
		description='Delay between clicks within the same round. Lower values make expiring visual challenges faster.',
	)


class VisionClickPoint(BaseModel):
	x: int = Field(ge=0, description='Horizontal click coordinate in the instructed screenshot plane.')
	y: int = Field(ge=0, description='Vertical click coordinate in the instructed screenshot plane.')


class VisionClickLoopDecision(BaseModel):
	status: Literal['click_more', 'click_finish', 'ready_to_submit'] = Field(
		description='Whether to click more image coordinates, click the final Submit/Verify control, or stop because the page is only ready to submit.'
	)
	clicks: list[VisionClickPoint] = Field(
		default_factory=list,
		description='Coordinates to click when status is click_more. Keep this list empty for other statuses.',
	)
	finish_click: VisionClickPoint | None = Field(
		default=None,
		description='Coordinate for the final Submit/Verify/Next/Skip control. Use with status=click_finish, or optionally alongside status=click_more for 4x4 grids where the button should be clicked immediately after the tile batch.',
	)
	final_round: bool = Field(
		default=False,
		description='Set true on a click_more decision when this batch is likely the FINAL selection step (e.g. all matches in a 3x3 grid clicked and no further replacement rounds expected). Triggers a single lightweight find-and-click of the Submit/Verify control instead of another full LLM round.',
	)
	reasoning: str = Field(description='Short explanation of the current visual judgment.')


class VisionFinishDecision(BaseModel):
	"""Lightweight decision used after a final_round=True click_more batch to find and click the Submit/Verify control."""

	status: Literal['click_finish', 'no_finish_visible', 'needs_more_clicks'] = Field(
		description='click_finish: the final control is visible; no_finish_visible: not yet visible (caller will fall through to a full round); needs_more_clicks: more selection clicks still required.'
	)
	finish_click: VisionClickPoint | None = Field(
		default=None,
		description='Coordinate of the Submit/Verify/Next control when status is click_finish.',
	)
	reasoning: str = Field(description='Short rationale.')


class PressAndHoldElementAction(BaseModel):
	"""Hybrid: provide either index OR (x, y). Index takes priority."""

	index: int | None = Field(default=None, ge=1, description='Element index (preferred when available)')
	x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')


class PressAndHoldElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='PressAndHoldElementAction')

	index: int = Field(ge=1, description='Element index')


class SwipeCoordinateAction(BaseModel):
	start_x: int = Field(description='Start horizontal coordinate relative to viewport left edge')
	start_y: int = Field(description='Start vertical coordinate relative to viewport top edge')
	end_x: int = Field(description='End horizontal coordinate relative to viewport left edge')
	end_y: int = Field(description='End vertical coordinate relative to viewport top edge')


class ScrollCoordinateAction(BaseModel):
	"""Hybrid: provide either index OR (x, y) to scroll at a specific element/point. Index takes priority."""

	index: int | None = Field(default=None, ge=1, description='Element index to scroll at (preferred when available)')
	x: int | None = Field(default=None, description='Horizontal coordinate to scroll at relative to viewport left edge')
	y: int | None = Field(default=None, description='Vertical coordinate to scroll at relative to viewport top edge')
	down: bool = Field(default=True, description='Scroll down (True) or up (False)')
	pages: float = Field(default=1.0, description='Number of pages to scroll.')


class ScrollCoordinateActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='ScrollCoordinateAction')

	index: int = Field(ge=1, description='Element index to scroll at')
	down: bool = Field(default=True, description='Scroll down (True) or up (False)')
	pages: float = Field(default=1.0, description='Number of pages to scroll.')


class SendKeysAction(BaseModel):
	keys: str = Field(description='keys (Escape, Enter, PageDown) or shortcuts (Control+o)')


class TypeAtAction(BaseModel):
	coordinate_x: int = Field(description='Horizontal coordinate (0-1000, normalized) of the input field to focus')
	coordinate_y: int = Field(description='Vertical coordinate (0-1000, normalized) of the input field to focus')
	text: str = Field(description='Text to type into the focused field')
	submit: bool = Field(default=False, description='Press Enter after typing (submit the field)')
	target_description: str | None = Field(default=None, description='Short description of the field, e.g. "search box"')
	cache_region: ClickCacheRegion | None = Field(default=None, description='Optional visual click context rect around the field, for cache anchor extraction (mirrors the click tool)')



class UploadFileAction(BaseModel):
	index: int
	path: str


class NoParamsAction(BaseModel):
	model_config = ConfigDict(extra='ignore')

	# Optional field required by Gemini API which errors on empty objects in response_schema
	description: str | None = Field(None, description='Optional description for the action')


class ScreenshotAction(BaseModel):
	model_config = ConfigDict(extra='ignore')

	file_name: str | None = Field(
		default=None,
		description='If provided, saves screenshot to this file and returns path. Otherwise screenshot is included in next observation.',
	)


class SaveAsPdfAction(BaseModel):
	file_name: str | None = Field(
		default=None,
		description='Output PDF filename (without path). Defaults to page title. Extension .pdf is added automatically if missing.',
	)
	print_background: bool = Field(default=True, description='Include background graphics and colors')
	landscape: bool = Field(default=False, description='Use landscape orientation')
	scale: float = Field(default=1.0, ge=0.1, le=2.0, description='Scale of the webpage rendering (0.1 to 2.0)')
	paper_format: str = Field(
		default='Letter',
		description='Paper size: Letter, Legal, A4, A3, or Tabloid',
	)


class GetDropdownOptionsAction(BaseModel):
	index: int


class SelectDropdownOptionAction(BaseModel):
	index: int
	text: str = Field(description='exact text/value')
