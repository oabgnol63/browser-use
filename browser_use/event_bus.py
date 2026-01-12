import asyncio
import logging
import os
from typing import Any, TypeVar
from bubus import EventBus as BubusEventBus
from bubus.service import BaseEvent, QueueShutDown, holds_global_lock
from contextvars import ContextVar

logger = logging.getLogger('bubus')

T_Event = TypeVar('T_Event', bound='BaseEvent[Any]')
T_ExpectedEvent = TypeVar('T_ExpectedEvent', bound='BaseEvent[Any]')

# Increase the hardcoded memory limit from 50MB to a more reasonable default for browser automation
# This prevents constant warnings when running multiple agents.
MEMORY_LIMIT_MB = int(os.getenv('BUBUS_MEMORY_LIMIT_MB', '512'))

def _patched_check_total_memory_usage(self) -> None:
	"""Patched version of bubus memory check with configurable limit."""
	import sys
	from collections import deque

	total_bytes = 0
	bus_details = []

	for bus in list(BubusEventBus.all_instances):
		try:
			bus_bytes = 0
			for event in bus.event_history.values():
				bus_bytes += sys.getsizeof(event)
				if hasattr(event, '__dict__'):
					for attr_value in event.__dict__.values():
						if isinstance(attr_value, (str, bytes, list, dict)):
							bus_bytes += sys.getsizeof(attr_value)

			if bus.event_queue:
				if hasattr(bus.event_queue, '_queue'):
					queue = bus.event_queue._queue
					for event in queue:
						bus_bytes += sys.getsizeof(event)
						if hasattr(event, '__dict__'):
							for attr_value in event.__dict__.values():
								if isinstance(attr_value, (str, bytes, list, dict)):
									bus_bytes += sys.getsizeof(attr_value)

			total_bytes += bus_bytes
			bus_details.append((bus.name, bus_bytes, len(bus.event_history), bus.event_queue.qsize() if bus.event_queue else 0))
		except Exception:
			continue

	total_mb = total_bytes / (1024 * 1024)

	if total_mb > MEMORY_LIMIT_MB:
		details = []
		for name, bytes_used, history_size, queue_size in sorted(bus_details, key=lambda x: x[1], reverse=True):
			mb = bytes_used / (1024 * 1024)
			if mb > 1.0: # Only show buses using >1MB
				details.append(f'  - {name}: {mb:.1f}MB (history={history_size}, queue={queue_size})')

		warning_msg = (
			f'\n WARNING: Total EventBus memory usage is {total_mb:.1f}MB (>{MEMORY_LIMIT_MB}MB limit)\n'
			f'Active EventBus instances: {len(BubusEventBus.all_instances)}\n'
		)
		if details:
			warning_msg += 'Memory breakdown (top buses):\n' + '\n'.join(details[:5])
		
		logger.warning(warning_msg)

# Apply the patch to the base class
BubusEventBus._check_total_memory_usage = _patched_check_total_memory_usage


class InstanceReentrantLock:
	"""
	A per-instance re-entrant lock that works across different asyncio tasks using ContextVar.
	
	Key differences from bubus's global ReentrantLock:
	1. Each EventBus instance gets its own lock (not shared globally)
	2. Depth tracking uses ContextVar (not instance variable) for proper async context isolation
	3. Sets bubus's holds_global_lock to allow nested processing within the same context
	"""

	def __init__(self, name: str):
		self._semaphore: asyncio.Semaphore | None = None
		self._loop: asyncio.AbstractEventLoop | None = None
		# Per-instance, per-context tracking
		self._holds_lock: ContextVar[bool] = ContextVar(f'holds_lock_{name}', default=False)
		self._depth: ContextVar[int] = ContextVar(f'lock_depth_{name}', default=0)

	def _get_semaphore(self) -> asyncio.Semaphore:
		"""Get or create the semaphore for the current event loop."""
		current_loop = asyncio.get_running_loop()
		if self._semaphore is None or self._loop != current_loop:
			# Create new semaphore for this event loop
			self._semaphore = asyncio.Semaphore(1)
			self._loop = current_loop
		return self._semaphore

	async def __aenter__(self):
		current_depth = self._depth.get()
		
		if self._holds_lock.get():
			# We already hold the lock in this context, increment depth
			self._depth.set(current_depth + 1)
			return self

		# Acquire the lock (this will block if another context holds it for THIS instance)
		await self._get_semaphore().acquire()
		self._holds_lock.set(True)
		self._depth.set(1)
		# Set bubus global lock context to allow nested processing within handlers
		holds_global_lock.set(True)
		return self

	async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
		if not self._holds_lock.get():
			# We don't hold the lock, nothing to do
			return

		current_depth = self._depth.get()
		new_depth = current_depth - 1
		self._depth.set(new_depth)
		
		if new_depth == 0:
			# Last exit, release the lock
			self._holds_lock.set(False)
			holds_global_lock.set(False)
			self._get_semaphore().release()

	def locked(self) -> bool:
		"""Check if the lock is currently held by any context."""
		try:
			current_loop = asyncio.get_running_loop()
			if self._semaphore is None or self._loop != current_loop:
				return False
			return self._semaphore.locked()
		except RuntimeError:
			return False

	def holds_lock(self) -> bool:
		"""Check if the current async context holds this lock."""
		return self._holds_lock.get()

class EventBus(BubusEventBus):
	"""
	Subclass of bubus.EventBus that uses a per-instance lock instead of a global lock.
	This allows multiple EventBus instances (e.g. from different agents) to run concurrently.
	
	Key changes from bubus.EventBus:
	1. step() uses per-instance lock instead of global _get_global_lock()
	2. process_event() also uses per-instance lock for calls from BaseEvent.__await__()
	3. event_queue.qsize() is monkey-patched to avoid cross-agent interference during polling
	4. default max_history_size is increased to 100 (bubus default is 50, previously reduced to 20)
	   to allow more context for cross-agent "helping" now that memory limit is increased.
	"""
	def __init__(self, *args, max_history_size: int | None = 100, **kwargs):
		# Increase default history size now that we have more memory allowed.
		# This helps when agents are helping each other by keeping more context alive.
		super().__init__(*args, max_history_size=max_history_size, **kwargs)
		self._instance_lock = InstanceReentrantLock(self.name)

	def _start(self) -> None:
		"""Start the event bus and apply concurrency protections."""
		super()._start()
		
		# Concurrency protection: Monkey-patch qsize to prevent this bus from being 
		# "helped" by other agents during their polling loops. This ensures
		# that Agent A's task doesn't block while trying to process Agent B's events.
		if self.event_queue and not hasattr(self.event_queue, '_qsize_patched'):
			original_qsize = self.event_queue.qsize
			
			def wrapped_qsize():
				# If we are in a polling loop (holds_global_lock is True)
				# but we don't hold the lock for THIS specific bus instance,
				# we lie and say the queue is empty if the bus is busy.
				# This prevents the polling loop from "stealing" events and blocking.
				if holds_global_lock.get() and not self._instance_lock.holds_lock():
					if self._instance_lock.locked():
						return 0
				return original_qsize()
				
			self.event_queue.qsize = wrapped_qsize
			self.event_queue._qsize_patched = True

	def dispatch(self, event: T_ExpectedEvent) -> T_ExpectedEvent:
		"""Override dispatch to increase default timeout for AgentFocusChangedEvent"""
		if event.event_type == 'AgentFocusChangedEvent' and event.event_timeout == 10.0:
			event.event_timeout = 30.0  # Increase to 30s to avoid timeouts under heavy load
		
		return super().dispatch(event)

	async def process_event(self, event: 'BaseEvent[Any]', timeout: float | None = None) -> None:
		"""
		Process a single event with instance lock protection.
		
		This override is necessary because BaseEvent.__await__() in bubus models.py
		directly calls bus.process_event() bypassing step(), which would bypass our
		per-instance lock. By adding lock protection here, we ensure thread-safety
		even when process_event is called from __await__() during child event polling.
		"""
		# Double-check concurrency protection: if we are a "helper" and the bus is busy,
		# don't block. Put the event back and yield. (Fallback for race conditions in qsize)
		if holds_global_lock.get() and not self._instance_lock.holds_lock():
			if self._instance_lock.locked():
				if self.event_queue:
					self.event_queue.put_nowait(event)
					await asyncio.sleep(0)  # Yield to let the owner task run
					return

		# Use instance lock to prevent concurrent processing on this bus
		async with self._instance_lock:
			await super().process_event(event, timeout=timeout)

	async def step(
		self, event: 'BaseEvent[Any] | None' = None, timeout: float | None = None, wait_for_timeout: float = 0.1
	) -> 'BaseEvent[Any] | None':
		"""Process a single event from the queue using instance lock"""
		assert self._on_idle and self.event_queue, 'EventBus._start() must be called before step()'

		# Track if we got the event from the queue
		from_queue = False

		# Wait for next event with timeout to periodically check idle state
		if event is None:
			event = await self._get_next_event(wait_for_timeout=wait_for_timeout)
			from_queue = True
		if event is None:
			return None

		logger.debug(f'🏃 {self}.step({event}) STARTING')

		# Clear idle state when we get an event
		self._on_idle.clear()

		# Use instance lock instead of global lock
		# Note: process_event also acquires the lock, but it's re-entrant so this works
		async with self._instance_lock:
			# Process the event
			await self.process_event(event, timeout=timeout)

			# Mark task as done only if we got it from the queue
			if from_queue:
				self.event_queue.task_done()

		logger.debug(f'✅ {self}.step({event}) COMPLETE')
		return event
