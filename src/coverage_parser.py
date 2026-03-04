"""Coverage parser helpers."""

from typing import Dict, List


def coverage_summary(coverage: Dict, version: str = "buggy") -> str:
	vdata = coverage.get(version)
	if not vdata:
		return f"No coverage data for version: {version}"
	method_cov = vdata.get("method_coverage", {}) or {}
	total_methods = len(method_cov)
	complex_methods: List[str] = []
	for m in method_cov.keys():
		if "Complex" in m:
			parts = m.split(".")
			name = parts[-1].split("(")[0] if parts else m
			complex_methods.append(name)
	coverage_pct = vdata.get("coverage", {}).get("coverage_percentage", 0)
	return (
		f"Coverage for {version}:\n"
		f"Total methods: {total_methods}\n"
		f"Complex methods: {len(complex_methods)}\n"
		f"Coverage percentage: {coverage_pct:.1%}\n"
		f"Sample Complex methods: {', '.join(sorted(set(complex_methods))[:10])}"
	)


def coverage_lines(coverage: Dict, method_name: str, version: str = "buggy") -> str:
	vdata = coverage.get(version)
	if not vdata:
		return f"No coverage data for version: {version}"
	method_cov = vdata.get("method_coverage", {}) or {}
	matched = []
	for sig, lines in method_cov.items():
		if method_name.lower() in sig.lower():
			matched.append((sig, lines))
	if not matched:
		return f"No method found containing '{method_name}'"
	out: List[str] = []
	for sig, lines in matched[:3]:
		if isinstance(lines, list):
			out.append(f"{sig}: {len(lines)} coverage points")
		else:
			out.append(f"{sig}: Coverage data format unknown")
	return "\n".join(out)

