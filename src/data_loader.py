"""Project data loader that wires coverage, callgraph, and test parsing."""

from typing import Dict, Any, Optional
from pathlib import Path
import json

from .callgraph_parser import parse_callgraph
from .test_parser import find_test_samples


class DataLoader:
	def __init__(self, root: Optional[Path] = None):
		self.root = root or Path(".")
		self.tests_root = None

	def load(self, coverage_path: str = "data/raw/cov.json", callgraph_csv: str = "data/raw/callgraph.csv", tests_root: str = "data/raw/test", prefer_string_utils: bool = True) -> Dict[str, Any]:
		"""Load coverage JSON, callgraph CSV, and test samples.
		
		Args:
			coverage_path: Path to coverage JSON (currently unused)
			callgraph_csv: Path to callgraph CSV file
			tests_root: Root directory for test files
			prefer_string_utils: If True, prefer callgraph_string_utils.csv if it exists (for backward compatibility)
		"""
		# Store tests_root for later use
		self.tests_root = tests_root
		
		# Coverage input disabled: return empty coverage payload
		coverage_data: Dict[str, Any] = {}

		# Load callgraph - optionally prefer StringUtils version for backward compatibility
		if prefer_string_utils:
			preferred_callgraph = Path("data/raw/callgraph_string_utils.csv")
			callgraph_path = str(preferred_callgraph) if preferred_callgraph.exists() else callgraph_csv
		else:
			callgraph_path = callgraph_csv
		callgraph_data = parse_callgraph(callgraph_path, limit=None)
		test_samples = find_test_samples(tests_root, max_samples=None)

		return {
			"coverage": coverage_data,
			"callgraph": callgraph_data,
			"tests": test_samples,
		}

