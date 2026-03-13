"""Result saving utilities for analysis and detailed logs."""

from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import json


def save_analysis(output_dir: Path, analysis: str, filename: Optional[str] = None) -> str:
	if not filename:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		filename = f"analysis_{timestamp}.txt"
	output_dir.mkdir(parents=True, exist_ok=True)
	filepath = output_dir / filename
	try:
		with open(filepath, "w", encoding="utf-8") as f:
			f.write(analysis)
		return f"Analysis saved to: {filepath}"
	except Exception as e:
		return f"Error saving analysis: {e}"


def save_detailed_log(output_dir: Path, state: Dict[str, Any], version: str) -> str:
	output_dir.mkdir(parents=True, exist_ok=True)
	log_data = {
		"task": state.get("task"),
		"version": version,
		"timestamp": datetime.now().isoformat(),
		"iterations": state.get("iteration"),
		"done": state.get("done"),
		"current_understanding": state.get("current_understanding"),
		"tools_output": state.get("tools_output"),
		"responses": state.get("responses"),
		"context": {
			"coverage": state.get("coverage_context"),
			"callgraph": state.get("callgraph_context"),
			"tests": state.get("test_context"),
		},
	}
	timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	filename = f"mlx_question_detailed_{version}_{timestamp}.json"
	filepath = output_dir / filename
	try:
		with open(filepath, "w", encoding="utf-8") as f:
			json.dump(log_data, f, indent=2, default=str)
		return f"Detailed log saved to: {filepath}"
	except Exception as e:
		return f"Error saving detailed log: {e}"

