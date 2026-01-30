/**
 * DOM Tree Extraction Script for Browser-Use
 * 
 * This script is injected into pages via Playwright's page.evaluate() to extract
 * DOM elements and their properties for Firefox and WebKit (Safari) browsers.
 * 
 * For Chromium browsers, the CDP-based approach in service.py is used instead.
 * 
 * @param {Object} args - Configuration arguments
 * @param {boolean} args.doHighlightElements - Whether to add visual highlights
 * @param {number} args.focusHighlightIndex - Element index to focus (-1 for none)
 * @param {number} args.viewportExpansion - Pixels to expand viewport detection
 * @param {boolean} args.debugMode - Enable debug logging
 * @returns {Object} - DOM tree data with map, rootId, and perfMetrics
 */
(function(args) {
	'use strict';

	const {
		doHighlightElements = true,
		focusHighlightIndex = -1,
		viewportExpansion = 0,
		debugMode = false
	} = args || {};

	// Performance tracking
	const perfMetrics = {
		startTime: performance.now(),
		nodeMetrics: {
			totalNodes: 0,
			processedNodes: 0,
			interactiveNodes: 0,
			visibleNodes: 0
		}
	};

	// Node map to store extracted data
	const nodeMap = {};
	let nodeIdCounter = 1;
	let highlightIndex = 0;

	// Highlight container for visual elements
	let highlightContainer = null;
	
	// Track interactive elements for sorted index assignment
	const interactiveElements = [];

	// Interactive element selectors
	const INTERACTIVE_SELECTORS = [
		'a[href]',
		'button',
		'input',
		'select',
		'textarea',
		'[role="button"]',
		'[role="link"]',
		'[role="checkbox"]',
		'[role="radio"]',
		'[role="tab"]',
		'[role="menuitem"]',
		'[role="option"]',
		'[role="switch"]',
		'[role="slider"]',
		'[role="spinbutton"]',
		'[role="combobox"]',
		'[role="listbox"]',
		'[role="searchbox"]',
		'[role="textbox"]',
		'[tabindex]',
		'[onclick]',
		'[contenteditable="true"]',
		'summary',
		'details',
		'label[for]',
		'[draggable="true"]'
	];

	// Elements to skip completely
	const SKIP_TAGS = new Set([
		'SCRIPT', 'STYLE', 'NOSCRIPT', 'META', 'LINK', 'HEAD', 'BR', 'HR'
	]);

	// Inline elements that shouldn't break text flow
	const INLINE_TAGS = new Set([
		'A', 'ABBR', 'ACRONYM', 'B', 'BDO', 'BIG', 'BR', 'BUTTON', 'CITE', 'CODE',
		'DFN', 'EM', 'I', 'IMG', 'INPUT', 'KBD', 'LABEL', 'MAP', 'OBJECT', 'Q',
		'SAMP', 'SCRIPT', 'SELECT', 'SMALL', 'SPAN', 'STRONG', 'SUB', 'SUP',
		'TEXTAREA', 'TIME', 'TT', 'VAR'
	]);

	/**
	 * Check if an element is visible in the viewport
	 */
	function isElementVisible(element) {
		if (!element || !element.getBoundingClientRect) return false;

		const style = window.getComputedStyle(element);
		if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
			return false;
		}

		const rect = element.getBoundingClientRect();
		if (rect.width === 0 && rect.height === 0) {
			return false;
		}

		return true;
	}

	/**
	 * Check if an element is in the viewport (with expansion)
	 */
	function isInViewport(element, expansion = 0) {
		if (!element || !element.getBoundingClientRect) return false;

		const rect = element.getBoundingClientRect();
		const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
		const viewportWidth = window.innerWidth || document.documentElement.clientWidth;

		return (
			rect.bottom >= -expansion &&
			rect.top <= viewportHeight + expansion &&
			rect.right >= -expansion &&
			rect.left <= viewportWidth + expansion
		);
	}

	/**
	 * Check if an element is interactive
	 */
	function isElementInteractive(element) {
		if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

		// Check if element matches interactive selectors
		for (const selector of INTERACTIVE_SELECTORS) {
			try {
				if (element.matches(selector)) return true;
			} catch (e) {
				// Invalid selector, skip
			}
		}

		// Check for click event listeners (heuristic)
		const tagName = element.tagName.toUpperCase();
		if (tagName === 'DIV' || tagName === 'SPAN') {
			const style = window.getComputedStyle(element);
			if (style.cursor === 'pointer') return true;
		}

		return false;
	}

	/**
	 * Check if element is the topmost element at its position
	 */
	function isTopElement(element) {
		if (!element || !element.getBoundingClientRect) return false;

		const rect = element.getBoundingClientRect();
		const centerX = rect.left + rect.width / 2;
		const centerY = rect.top + rect.height / 2;

		// Check if center point is within viewport
		if (centerX < 0 || centerY < 0 ||
			centerX > window.innerWidth || centerY > window.innerHeight) {
			return false;
		}

		try {
			const topElement = document.elementFromPoint(centerX, centerY);
			return topElement === element || element.contains(topElement);
		} catch (e) {
			return false;
		}
	}

	/**
	 * Get element attributes as a clean object
	 */
	function getElementAttributes(element) {
		const attrs = {};
		if (!element.attributes) return attrs;

		for (const attr of element.attributes) {
			// Skip internal/noisy attributes
			if (attr.name.startsWith('data-reactid') ||
				attr.name.startsWith('data-reactroot') ||
				attr.name.startsWith('ng-') ||
				attr.name === 'style') {
				continue;
			}
			attrs[attr.name] = attr.value;
		}

		return attrs;
	}

	/**
	 * Get text content for a node
	 */
	function getNodeText(node) {
		if (node.nodeType === Node.TEXT_NODE) {
			return node.textContent.trim();
		}
		if (node.nodeType === Node.ELEMENT_NODE) {
			// For input elements, get value
			if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') {
				return node.value || node.placeholder || '';
			}
			// For select elements, get selected option text
			if (node.tagName === 'SELECT' && node.selectedOptions && node.selectedOptions.length > 0) {
				return node.selectedOptions[0].textContent.trim();
			}
		}
		return '';
	}

	/**
	 * Create highlight overlay for an element
	 */
	function createHighlight(element, index, isFocused, isTopElement) {
		// Skip creating highlights for hidden elements (covered by other elements)
		if (isTopElement === false) {
			return;
		}
		
		if (!highlightContainer) {
			highlightContainer = document.createElement('div');
			highlightContainer.id = 'browser-use-highlight-container';
			highlightContainer.style.cssText = `
				position: fixed;
				top: 0;
				left: 0;
				width: 100%;
				height: 100%;
				pointer-events: none;
				z-index: 2147483647;
			`;
			document.body.appendChild(highlightContainer);
		}

		const rect = element.getBoundingClientRect();
		const highlight = document.createElement('div');
		highlight.className = 'browser-use-highlight';
		highlight.setAttribute('data-highlight-index', index);

		const color = isFocused ? 'rgba(255, 127, 39, 0.5)' : 'rgba(255, 127, 39, 0.3)';
		const borderColor = isFocused ? 'rgb(255, 127, 39)' : 'rgba(255, 127, 39, 0.8)';

		highlight.style.cssText = `
			position: fixed;
			left: ${rect.left}px;
			top: ${rect.top}px;
			width: ${rect.width}px;
			height: ${rect.height}px;
			background-color: ${color};
			border: 2px solid ${borderColor};
			box-sizing: border-box;
			pointer-events: none;
		`;

		// Add index label
		const label = document.createElement('span');
		label.style.cssText = `
			position: absolute;
			top: -18px;
			left: 0;
			background-color: rgb(255, 127, 39);
			color: white;
			padding: 2px 6px;
			font-size: 11px;
			font-family: monospace;
			border-radius: 3px;
			white-space: nowrap;
		`;
		label.textContent = String(index);
		highlight.appendChild(label);

		highlightContainer.appendChild(highlight);
	}

	/**
	 * Process a single DOM node
	 */
	function processNode(node, parentId) {
		const nodeId = nodeIdCounter++;
		perfMetrics.nodeMetrics.totalNodes++;

		// Handle text nodes
		if (node.nodeType === Node.TEXT_NODE) {
			const text = node.textContent.trim();
			if (!text) return null;

			const isVisible = node.parentElement ? isElementVisible(node.parentElement) : false;
			if (isVisible) perfMetrics.nodeMetrics.visibleNodes++;

			nodeMap[nodeId] = {
				type: 'TEXT_NODE',
				text: text,
				isVisible: isVisible,
				children: []
			};

			perfMetrics.nodeMetrics.processedNodes++;
			return nodeId;
		}

		// Skip non-element nodes
		if (node.nodeType !== Node.ELEMENT_NODE) {
			return null;
		}

		// Skip certain tags
		if (SKIP_TAGS.has(node.tagName)) {
			return null;
		}

		const isVisible = isElementVisible(node);
		const inViewport = isInViewport(node, viewportExpansion);
		const isInteractive = isElementInteractive(node);
		const isTop = isTopElement(node);

		if (isVisible) perfMetrics.nodeMetrics.visibleNodes++;

		// Get element bounds
		const rect = node.getBoundingClientRect();
		const viewport = {
			x: rect.left + window.scrollX,
			y: rect.top + window.scrollY,
			width: rect.width,
			height: rect.height
		};

		// Collect interactive elements for later sorted index assignment
		let currentHighlightIndex = null;
		if (isInteractive && isVisible && (inViewport || viewportExpansion > 0)) {
			perfMetrics.nodeMetrics.interactiveNodes++;
			// Store for later sorting by visual position
			interactiveElements.push({
				nodeId: nodeId,
				element: node,
				rect: rect,
				isTop: isTop
			});
			// Assign a temporary placeholder (will be updated after sorting)
			currentHighlightIndex = -1;
		}

		// Process children
		const childIds = [];
		for (const child of node.childNodes) {
			const childId = processNode(child, nodeId);
			if (childId !== null) {
				childIds.push(childId);
			}
		}

		// Get node text (direct text, not from children)
		let directText = '';
		for (const child of node.childNodes) {
			if (child.nodeType === Node.TEXT_NODE) {
				const text = child.textContent.trim();
				if (text) directText += text + ' ';
			}
		}
		directText = directText.trim();

		// Build node data
		const nodeData = {
			tagName: node.tagName.toLowerCase(),
			attributes: getElementAttributes(node),
			xpath: getXPath(node),
			isVisible: isVisible,
			isInteractive: isInteractive,
			isTopElement: isTop,
			isInViewport: inViewport,
			highlightIndex: currentHighlightIndex,
			shadowRoot: !!node.shadowRoot,
			viewport: viewport,
			children: childIds,
			text: directText || getNodeText(node),
			ariaLabel: node.getAttribute('aria-label'),
			ariaDescription: node.getAttribute('aria-describedby'),
			title: node.getAttribute('title'),
			role: node.getAttribute('role'),
			isScrollable: node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth
		};

		nodeMap[nodeId] = nodeData;
		perfMetrics.nodeMetrics.processedNodes++;

		return nodeId;
	}

	/**
	 * Generate XPath for an element
	 */
	function getXPath(element) {
		if (!element) return '';
		if (element.id) return `//*[@id="${element.id}"]`;

		const parts = [];
		let current = element;

		while (current && current.nodeType === Node.ELEMENT_NODE) {
			let index = 1;
			let sibling = current.previousSibling;

			while (sibling) {
				if (sibling.nodeType === Node.ELEMENT_NODE &&
					sibling.tagName === current.tagName) {
					index++;
				}
				sibling = sibling.previousSibling;
			}

			const tagName = current.tagName.toLowerCase();
			const part = index > 1 ? `${tagName}[${index}]` : tagName;
			parts.unshift(part);

			current = current.parentNode;
		}

		return '/' + parts.join('/');
	}

	/**
	 * Process shadow DOM roots
	 */
	function processShadowRoots(element, parentId) {
		if (!element.shadowRoot) return;

		for (const child of element.shadowRoot.childNodes) {
			processNode(child, parentId);
		}
	}

	// Main execution
	try {
		// Start from document body
		const rootId = processNode(document.body, null);

		// Sort interactive elements by visual position (top-to-bottom, left-to-right)
		interactiveElements.sort((a, b) => {
			const rectA = a.rect;
			const rectB = b.rect;
			
			// Primary sort: top position
			const topDiff = rectA.top - rectB.top;
			if (Math.abs(topDiff) > 5) { // 5px tolerance for "same row"
				return topDiff;
			}
			
			// Secondary sort: left position (for elements on same row)
			return rectA.left - rectB.left;
		});

		if (debugMode) {
			console.log(`[Browser-Use DOM] Sorted ${interactiveElements.length} interactive elements by visual position`);
		}

		// Assign highlight indices to all interactive elements (stable indices for LLM)
		// Visual highlights will be filtered in createHighlight to only show top elements
		if (debugMode) {
			console.log(`[Browser-Use DOM] About to assign indices to ${interactiveElements.length} elements`);
		}
		
		interactiveElements.forEach((item, index) => {
			const nodeData = nodeMap[item.nodeId];
			if (nodeData) {
				// Update the highlightIndex in the actual nodeMap
				nodeMap[item.nodeId].highlightIndex = index;
				// Store isTopElement for visual filtering
				nodeMap[item.nodeId].isTopElement = item.isTop;
				
				if (debugMode && index < 15) {
					console.log(`[Browser-Use DOM] Assigned index ${index} to ${nodeData.tagName} nodeId=${item.nodeId}`);
				}
				
				// Create visual highlight if enabled (only for topmost elements)
					if (doHighlightElements) {
						const isFocused = focusHighlightIndex === index;
						createHighlight(item.element, index, isFocused, item.isTop);
					}
			} else {
				if (debugMode) {
					console.warn(`[Browser-Use DOM] WARNING: nodeId ${item.nodeId} not found in nodeMap!`);
				}
			}
		});

		// Verify the update worked (AFTER the forEach)
		if (debugMode && interactiveElements.length > 0) {
			const firstInteractive = interactiveElements[0];
			const verifyNode = nodeMap[firstInteractive.nodeId];
			console.log(`[Browser-Use DOM] ✅ Verification - nodeMap[${firstInteractive.nodeId}].highlightIndex = ${verifyNode ? verifyNode.highlightIndex : 'NOT_FOUND'} (should be 0)`);
		}

		// Calculate final metrics
		perfMetrics.endTime = performance.now();
		perfMetrics.totalTime = perfMetrics.endTime - perfMetrics.startTime;

		if (debugMode) {
			console.log('[Browser-Use DOM] Extraction complete:', {
				totalNodes: perfMetrics.nodeMetrics.totalNodes,
				processedNodes: perfMetrics.nodeMetrics.processedNodes,
				interactiveNodes: perfMetrics.nodeMetrics.interactiveNodes,
				visibleNodes: perfMetrics.nodeMetrics.visibleNodes,
				totalTimeMs: perfMetrics.totalTime.toFixed(2)
			});
		}

		return {
			map: nodeMap,
			rootId: rootId,
			perfMetrics: perfMetrics
		};

	} catch (error) {
		console.error('[Browser-Use DOM] Extraction error:', error);
		return {
			map: {},
			rootId: null,
			perfMetrics: perfMetrics,
			error: error.message
		};
	}
})
