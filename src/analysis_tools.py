"""Analysis tools built on loaded project data.

Includes helpers for coverage summaries, callgraph querying, method bodies,
test listing and retrieval. Does not perform file writes – use result_saver.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional

from .coverage_parser import coverage_summary, coverage_lines
from .test_parser import get_tests_for_class as _tests_for_class, get_test_content as _get_test_content, find_test_samples


class AnalysisTools:
	def __init__(self, project_data: Dict[str, Any], output_dir: Optional[Path] = None, tests_root: str = "data/raw/test"):
		self.project_data = project_data
		self.output_dir = output_dir or Path("data/outputs/reconstructions")
		self.tests_root = tests_root

	# coverage
	def get_coverage_info(self, version: str = "buggy") -> str:
		return coverage_summary(self.project_data.get("coverage", {}), version)

	def get_coverage_lines(self, method_name: str, version: str = "buggy") -> str:
		return coverage_lines(self.project_data.get("coverage", {}), method_name, version)

	# callgraph
	def get_callgraph(self, method_filter: str = None) -> str:
		callgraph = self.project_data.get("callgraph", {})
		relationships = callgraph.get("relationships", [])
		if method_filter:
			# Normalize filter into a list of lowercase strings
			if isinstance(method_filter, list):
				filters = [str(item).lower() for item in method_filter if item is not None]
			else:
				filters = [str(method_filter).lower()]
			filtered: List[str] = []
			for rel in relationships:
				caller = rel.get("caller", "")
				callee = rel.get("callee", "")
				caller_lower = caller.lower()
				callee_lower = callee.lower()
				if any(f in caller_lower or f in callee_lower for f in filters):
					caller_simple = caller.split(".")[-1] if "." in caller else caller
					callee_simple = callee.split(".")[-1] if "." in callee else callee
					filtered.append(f"{caller_simple} → {callee_simple}")
			if filtered:
				filter_label = ", ".join(filters)
				return f"Relationships with '{filter_label}':\n" + "\n".join(filtered[:15])
			else:
				filter_label = ", ".join(filters)
				return f"No relationships found with '{filter_label}'"
		total = len(relationships)
		samples: List[str] = []
		for rel in relationships[:10]:
			caller = rel.get("caller", "")
			callee = rel.get("callee", "")
			caller_simple = caller.split(".")[-1] if "." in caller else caller
			callee_simple = callee.split(".")[-1] if "." in callee else callee
			samples.append(f"{caller_simple} → {callee_simple}")
		return f"Total relationships: {total}\nSample:\n" + "\n".join(samples)

	def get_method_body(self, method_name: str) -> str:
		method_bodies = self.project_data.get("callgraph", {}).get("method_bodies", {})
		if not method_bodies:
			return f"No method bodies loaded. Ensure callgraph CSV is parsed fully."

		# Normalize requested method name like 'Class.method()', 'method()', 'pkg.Class:method'
		requested = (method_name or "").strip()
		# Strip parameters/parentheses
		import re
		requested = re.sub(r"\(.*\)$", "", requested)
		# If qualified, keep the method token after last '.' or ':'
		if "." in requested:
			requested_simple = requested.split(".")[-1]
		elif ":" in requested:
			requested_simple = requested.split(":")[-1]
		else:
			requested_simple = requested

		req_lower = requested_simple.lower()
		matches: List[str] = []

		# 1) Exact class:method match if keys use 'Class:method'
		for sig, body in method_bodies.items():
			if ":" in sig:
				method_token = sig.split(":")[-1].lower()
				if method_token == req_lower:
					clean = body.strip()
					if len(clean) > 500:
						clean = clean[:500] + "..."
					matches.append(f"Method: {sig}\n```java\n{clean}\n```")

		# 2) Signature header match 'access_modifier return_type name(params)'
		if not matches:
			pattern = re.compile(rf"\b{re.escape(requested_simple)}\s*\(", re.IGNORECASE)
			for sig, body in method_bodies.items():
				if pattern.search(sig):
					clean = body.strip()
					if len(clean) > 500:
						clean = clean[:500] + "..."
					matches.append(f"Method: {sig}\n```java\n{clean}\n```")

		# 3) Fallback substring match
		if not matches:
			for sig, body in method_bodies.items():
				if req_lower in sig.lower():
					clean = body.strip()
					if len(clean) > 500:
						clean = clean[:500] + "..."
					matches.append(f"Method: {sig}\n```java\n{clean}\n```")

		if not matches:
			available = list(method_bodies.keys())[:10]
			return f"No method body found for '{method_name}'. Examples: {', '.join(available)}"
		return "\n\n".join(matches[:2])

	# tests
	def get_tests_for_class(self, class_name: str) -> str:
		tests = self.project_data.get("tests", [])
		return _tests_for_class(tests, class_name)

	def get_test_content(self, filename: str) -> str:
		return _get_test_content(filename, tests_root=self.tests_root)

	def get_all_tests(self, limit: Optional[int] = None, include_samples: bool = False, force_refresh: bool = False) -> str:
		tests = self.project_data.get("tests", [])
		if force_refresh or not tests or (limit is None and len(tests) < 3):
			tests = find_test_samples(self.tests_root, max_samples=None)
			self.project_data["tests"] = tests
		if not tests:
			return "No tests found"
		lines: List[str] = [f"Total tests discovered: {len(tests)}"]
		shown = 0
		for t in tests:
			if limit is not None and shown >= limit:
				break
			lines.append(f"- {t.get('class','Unknown')} ({t.get('file','')})")
			if include_samples and t.get("sample"):
				lines.append(f"```java\n{t['sample'][:400]}\n```")
			shown += 1
		if limit is not None and len(tests) > limit:
			lines.append(f"...and {len(tests) - limit} more")
		return "\n".join(lines)

