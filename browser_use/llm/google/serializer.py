import base64

from google.genai.types import Content, ContentListUnion, Part, PartMediaResolutionLevel

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	SystemMessage,
	UserMessage,
)
from browser_use.utils import sanitize_surrogates


class GoogleMessageSerializer:
	"""Serializer for converting messages to Google Gemini format."""

	@staticmethod
	def _serialize_image_part(part: ContentPartImageParam) -> Part:
		"""Serialize image parts for Gemini, mapping detail to Gemini media resolution."""
		url = part.image_url.url

		# Format: data:image/jpeg;base64,<data>
		_header, data = url.split(',', 1)
		image_bytes = base64.b64decode(data)

		return Part.from_bytes(
			data=image_bytes,
			mime_type=part.image_url.media_type,
			media_resolution=GoogleMessageSerializer._map_media_resolution(part.image_url.detail),
		)

	@staticmethod
	def _map_media_resolution(detail: str) -> PartMediaResolutionLevel | None:
		"""Map Browser Use image detail to Gemini media resolution."""
		if detail == 'low':
			return PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW
		if detail == 'high':
			return PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH
		return None

	@staticmethod
	def serialize_messages(
		messages: list[BaseMessage], include_system_in_user: bool = False
	) -> tuple[ContentListUnion, str | None]:
		"""
		Convert a list of BaseMessages to Google format, extracting system message.

		Google handles system instructions separately from the conversation, so we need to:
		1. Extract any system messages and return them separately as a string (or include in first user message if flag is set)
		2. Convert the remaining messages to Content objects

		Args:
		    messages: List of messages to convert
		    include_system_in_user: If True, system/developer messages are prepended to the first user message

		Returns:
		    A tuple of (formatted_messages, system_message) where:
		    - formatted_messages: List of Content objects for the conversation
		    - system_message: System instruction string or None
		"""

		messages = [m.model_copy(deep=True) for m in messages]

		formatted_messages: ContentListUnion = []
		system_message: str | None = None
		system_parts: list[str] = []

		for i, message in enumerate(messages):
			role = message.role if hasattr(message, 'role') else None

			# Handle system/developer messages
			if isinstance(message, SystemMessage) or role in ['system', 'developer']:
				# Extract system message content as string
				if isinstance(message.content, str):
					content = sanitize_surrogates(message.content)
					if include_system_in_user:
						system_parts.append(content)
					else:
						system_message = content
				elif message.content is not None:
					# Handle Iterable of content parts
					parts = []
					for part in message.content:
						if part.type == 'text':
							parts.append(sanitize_surrogates(part.text))
					combined_text = '\n'.join(parts)
					if include_system_in_user:
						system_parts.append(combined_text)
					else:
						system_message = combined_text
				continue

			# Determine the role for non-system messages
			if isinstance(message, UserMessage):
				role = 'user'
			elif isinstance(message, AssistantMessage):
				role = 'model'
			else:
				# Default to user for any unknown message types
				role = 'user'

			# Initialize message parts
			message_parts: list[Part] = []

			# If this is the first user message and we have system parts, prepend them
			if include_system_in_user and system_parts and role == 'user' and not formatted_messages:
				system_text = '\n\n'.join(system_parts)
				if isinstance(message.content, str):
					content = sanitize_surrogates(message.content)
					message_parts.append(Part.from_text(text=f'{system_text}\n\n{content}'))
				else:
					# Add system text as the first part
					message_parts.append(Part.from_text(text=system_text))
				system_parts = []  # Clear after using
			else:
				# Extract content and create parts normally
				if isinstance(message.content, str):
					# Regular text content
					message_parts = [Part.from_text(text=sanitize_surrogates(message.content))]
				elif message.content is not None:
					# Handle Iterable of content parts
					for part in message.content:
						if part.type == 'text':
							message_parts.append(Part.from_text(text=sanitize_surrogates(part.text)))
						elif part.type == 'refusal':
							message_parts.append(Part.from_text(text=f'[Refusal] {part.refusal}'))
						elif part.type == 'image_url':
							message_parts.append(GoogleMessageSerializer._serialize_image_part(part))

			# Create the Content object
			if message_parts:
				final_message = Content(role=role, parts=message_parts)
				# for some reason, the type checker is not able to infer the type of formatted_messages
				formatted_messages.append(final_message)  # type: ignore

		return formatted_messages, system_message
