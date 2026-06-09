import base64
from io import BytesIO

from google.genai.types import PartMediaResolutionLevel
from PIL import Image

from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import ContentPartImageParam, ImageURL, UserMessage


def _make_base64_png(size: tuple[int, int]) -> str:
	buffer = BytesIO()
	Image.new('RGB', size, color=(255, 0, 0)).save(buffer, format='PNG')
	return base64.b64encode(buffer.getvalue()).decode('utf-8')


def test_google_serializer_sets_low_media_resolution():
	image_b64 = _make_base64_png((1600, 900))
	message = UserMessage(
		content=[
			ContentPartImageParam(
				image_url=ImageURL(
					url=f'data:image/png;base64,{image_b64}',
					media_type='image/png',
					detail='low',
				)
			)
		]
	)

	formatted_messages, system_message = GoogleMessageSerializer.serialize_messages([message])

	assert system_message is None
	part = formatted_messages[0].parts[0]
	assert part.media_resolution is not None
	assert part.media_resolution.level == PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW
	assert part.inline_data is not None


def test_google_serializer_sets_high_media_resolution():
	image_b64 = _make_base64_png((1600, 900))
	message = UserMessage(
		content=[
			ContentPartImageParam(
				image_url=ImageURL(
					url=f'data:image/png;base64,{image_b64}',
					media_type='image/png',
					detail='high',
				)
			)
		]
	)

	formatted_messages, _system_message = GoogleMessageSerializer.serialize_messages([message])

	part = formatted_messages[0].parts[0]
	assert part.media_resolution is not None
	assert part.media_resolution.level == PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH
	assert part.inline_data is not None


def test_google_serializer_leaves_auto_media_resolution_unset():
	image_b64 = _make_base64_png((1600, 900))
	message = UserMessage(
		content=[
			ContentPartImageParam(
				image_url=ImageURL(
					url=f'data:image/png;base64,{image_b64}',
					media_type='image/png',
					detail='auto',
				)
			)
		]
	)

	formatted_messages, _system_message = GoogleMessageSerializer.serialize_messages([message])

	part = formatted_messages[0].parts[0]
	assert part.media_resolution is None
	assert part.inline_data is not None
