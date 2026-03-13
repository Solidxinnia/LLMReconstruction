# Callgraph CSV parser utilities.

from typing import Dict, Any, List, Optional


def parse_callgraph(csv_path: str, limit: Optional[int] = 100) -> Dict[str, Any]:
	"""Parse a callgraph CSV file.

	Returns a dict with keys: relationships (list of {caller, callee}),
	method_bodies (dict signature->body snippet), total_relationships, total_method_bodies.
	"""
	import csv

	relationships: List[Dict[str, str]] = []
	method_bodies: Dict[str, str] = {}

	try:
		with open(csv_path, "r", encoding="utf-8-sig") as f:
			reader = csv.DictReader(f)
			for i, row in enumerate(reader):
				if limit and i >= limit:
					break
				caller = (row.get("caller", "") or "").strip()
				callee = (row.get("callee", "") or "").strip()
				if caller and callee:
					relationships.append({"caller": caller, "callee": callee})

				caller_body = (row.get("caller_body", "") or "").strip()
				callee_body = (row.get("callee_body", "") or "").strip()
				if caller_body and caller_body not in ["BODY_NOT_FOUND", ""]:
					method_bodies[caller] = caller_body[:1000]
				if callee_body and callee_body not in ["BODY_NOT_FOUND", ""]:
					method_bodies[callee] = callee_body[:1000]

		return {
			"relationships": relationships,
			"method_bodies": method_bodies,
			"total_relationships": len(relationships),
			"total_method_bodies": len(method_bodies),
		}
	except Exception:
		return {"relationships": [], "method_bodies": {}, "total_relationships": 0, "total_method_bodies": 0}

