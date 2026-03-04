#!/usr/bin/env python3
"""
Coverage Comparison Tool for LLM Execution Paths vs Defects4J Coverage

Compares LLM-predicted execution paths against ground-truth coverage from Defects4J.
Outputs results in the same format as Defects4J method_coverage JSON.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict


class CoverageComparator:
    """Compare LLM execution paths with Defects4J coverage data"""
    
    def __init__(self, defects4j_json_path: str, llm_report_path: str):
        self.defects4j_json_path = defects4j_json_path
        self.llm_report_path = llm_report_path
        
        self.coverage_methods = {}  # Ground truth: method -> lines
        self.llm_methods = []  # LLM predicted methods
        self.llm_method_set = set()  # For quick lookup
        self.llm_method_coverage = {}  # LLM method_coverage JSON (if present)
        
    def load_defects4j_coverage(self, bug_id: str = None) -> Dict[str, List[str]]:
        """
        Load method coverage from Defects4J JSON
        
        Returns:
            Dict mapping method signature to list of line coverage entries
            Example: {
                "org.apache.commons.math3.complex.Complex.<init>(DD)V": [
                    "98|0",
                    "99|0",
                    "102|0|0% (0/4)",
                    ...
                ]
            }
        """
        with open(self.defects4j_json_path, 'r') as f:
            data = json.load(f)
        
        # If no bug_id specified, try to find the first available one
        if bug_id is None:
            bugs = data.get('bugs', {})
            if bugs:
                bug_id = list(bugs.keys())[0]
                print(f"📊 Auto-selected bug ID: {bug_id}")
        
        if 'bugs' in data and bug_id in data['bugs']:
            method_coverage = data['bugs'][bug_id].get('method_coverage', {})
            self.coverage_methods = method_coverage
            print(f"✓ Loaded {len(method_coverage)} methods from Defects4J coverage (bug {bug_id})")
            return method_coverage
        else:
            print(f"⚠️  Bug ID '{bug_id}' not found in JSON")
            return {}
    
    def load_llm_report(self) -> List[str]:
        """
        Load LLM execution output from orchestrator report.

        Supports two formats:
        1) JSON with method_coverage (preferred)
        2) Legacy "Methods/Lines to Execute" list

        Returns:
            List of method signatures predicted by LLM
        """
        try:
            content = Path(self.llm_report_path).read_text(encoding='utf-8')
        except FileNotFoundError:
            print(f"⚠️  LLM report not found: {self.llm_report_path}")
            return []

        # Try to parse method_coverage JSON embedded in the report
        method_coverage = self._extract_method_coverage_json(content)
        if method_coverage:
            self.llm_method_coverage = method_coverage
            self.llm_methods = list(method_coverage.keys())
            self.llm_method_set = set(self.llm_methods)
            print(f"✓ Loaded {len(self.llm_methods)} methods from LLM method_coverage JSON")
            return self.llm_methods
        
        # Find the execution path section
        methods = []
        in_execution_section = False
        found_methods_header = False
        
        for line in content.split('\n'):
            # Look for "Methods/Lines to Execute:" specifically
            if 'Methods/Lines to Execute:' in line:
                found_methods_header = True
                in_execution_section = True
                continue
            
            if in_execution_section and found_methods_header:
                # Stop at next major section (TOOL EXECUTION, next ===)
                if 'TOOL EXECUTION' in line:
                    break
                
                # Skip section dividers but don't stop
                if line.strip().startswith('==='):
                    continue
                
                # Skip empty lines and "None identified"
                if not line.strip() or 'None identified' in line:
                    continue
                
                # Extract method signature from numbered list
                # Format: "1. org.apache.commons.math3.complex.Complex:method"
                match = re.match(r'^\s*\d+\.\s*(.+)', line)
                if match:
                    method_sig = match.group(1).strip()
                    if method_sig and not method_sig.startswith('='):
                        methods.append(method_sig)
        
        self.llm_methods = methods
        self.llm_method_set = set(methods)
        print(f"✓ Loaded {len(methods)} methods from LLM report")
        return methods

    def extract_simple_method_name(self, signature: str) -> str:
        """Extract simple method name from a method signature."""
        if not signature:
            return ""
        if ':' in signature:
            method_part = signature.split(':', 1)[1]
        else:
            method_part = signature.rsplit('.', 1)[-1]
        return method_part.split('(')[0].strip()

    def _normalize_coverage_entries_by_index(self, entries: List[str]) -> List[str]:
        """Normalize coverage entries so line numbers are 1..N based on list position.

        Filters out entries with 0 hit count (e.g., "5|0" or "5|0|0% (0/2)").
        """
        normalized = []
        for idx, entry in enumerate(entries, start=1):
            if '|' in entry:
                _, rest = entry.split('|', 1)
                parts = rest.split('|', 1)
                hit_count = parts[0].strip()
                if hit_count == "0":
                    continue
                normalized.append(f"{idx}|{rest}")
            else:
                if entry.strip() == "0":
                    continue
                normalized.append(f"{idx}|{entry}")
        return normalized

    def compare_by_method_name(self, bug_id: str) -> Dict[str, Dict[str, List[str]]]:
        """
        Compare LLM vs coverage by matching on simple method name only.
        Line numbers in coverage are normalized to 1..N based on list order.
        """
        if not self.coverage_methods:
            self.load_defects4j_coverage(bug_id)
        if not self.llm_method_coverage:
            self.load_llm_report()

        coverage_by_name = defaultdict(list)
        for sig, entries in self.coverage_methods.items():
            method_name = self.extract_simple_method_name(sig)
            coverage_by_name[method_name].append((sig, entries))

        report = {}
        for llm_sig, llm_entries in self.llm_method_coverage.items():
            method_name = self.extract_simple_method_name(llm_sig)
            coverage_matches = coverage_by_name.get(method_name, [])
            if not coverage_matches:
                report[llm_sig] = {
                    "coverage_matches": [],
                    "llm_entries": llm_entries,
                    "note": f"No coverage method with name '{method_name}' found in bug {bug_id}."
                }
                continue

            match_reports = []
            for coverage_sig, coverage_entries in coverage_matches:
                normalized_coverage = self._normalize_coverage_entries_by_index(coverage_entries)
                llm_set = set(llm_entries)
                coverage_set = set(normalized_coverage)

                match_reports.append({
                    "coverage_signature": coverage_sig,
                    "normalized_coverage_entries": normalized_coverage,
                    "llm_entries": llm_entries,
                    "missing_in_llm": sorted(coverage_set - llm_set),
                    "extra_in_llm": sorted(llm_set - coverage_set),
                    "exact_matches": sorted(coverage_set & llm_set),
                })

            report[llm_sig] = {
                "coverage_matches": match_reports,
                "note": f"Matched by method name '{method_name}'. Coverage line numbers normalized to 1..N."
            }

        return report

    def _extract_method_coverage_json(self, content: str) -> Dict[str, List[str]]:
        """Extract method_coverage JSON object from LLM report content."""
        # Prefer extracting JSON from the METHOD COVERAGE section
        section_match = re.search(
            r"METHOD COVERAGE \(LINE-LEVEL\).*?\n\n(\{.*?\})\s*(?:\n=+|\Z)",
            content,
            re.DOTALL
        )
        if section_match:
            json_text = section_match.group(1)
        else:
            # Fallback: find the first JSON object in the report
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if not json_match:
                return {}
            json_text = json_match.group(0)

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            return {}

        # Preferred format: {"method_coverage": {...}}
        method_coverage = data.get("method_coverage") if isinstance(data, dict) else None
        if isinstance(method_coverage, dict):
            return method_coverage

        # Alternate format: JSON is directly the method_coverage dict
        if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
            return data

        return {}
    
    def normalize_method_signature(self, sig: str) -> str:
        """
        Normalize method signatures to a common format for comparison
        
        Coverage format: org.apache.commons.math3.complex.Complex.<init>(DD)V
        LLM format: org.apache.commons.math3.complex.Complex:Complex(double,double)
        
        This is a simplified normalization. You may need to enhance it.
        """
        # For now, just extract the class and method name
        # More sophisticated matching would require parsing JVM descriptors
        
        if ':' in sig:
            # LLM format: Class:method
            parts = sig.split(':')
            return parts[0] + '.' + parts[1].split('(')[0]
        elif '.' in sig:
            # Coverage format: already has dots
            class_method = sig.split('(')[0]  # Remove parameters
            return class_method
        
        return sig
    
    def compare(self) -> Dict[str, any]:
        """
        Compare LLM predictions with ground truth coverage
        
        Returns:
            Comparison report with matches, missing, and extra methods
        """
        coverage_set = set(self.coverage_methods.keys())
        llm_set = self.llm_method_set
        
        # Exact matches
        exact_matches = coverage_set & llm_set
        
        # Missing: in coverage but not predicted by LLM
        missing = coverage_set - llm_set
        
        # Extra: predicted by LLM but not in coverage
        extra = llm_set - coverage_set
        
        # Try normalized matching for methods that didn't match exactly
        normalized_coverage = {
            self.normalize_method_signature(m): m 
            for m in coverage_set
        }
        normalized_llm = {
            self.normalize_method_signature(m): m 
            for m in llm_set
        }
        
        normalized_matches = set(normalized_coverage.keys()) & set(normalized_llm.keys())
        
        return {
            'exact_matches': sorted(exact_matches),
            'missing_methods': sorted(missing),
            'extra_methods': sorted(extra),
            'normalized_matches': len(normalized_matches),
            'total_coverage_methods': len(coverage_set),
            'total_llm_methods': len(llm_set),
            'exact_precision': len(exact_matches) / len(llm_set) if llm_set else 0,
            'exact_recall': len(exact_matches) / len(coverage_set) if coverage_set else 0,
            'normalized_precision': len(normalized_matches) / len(normalized_llm) if normalized_llm else 0,
            'normalized_recall': len(normalized_matches) / len(normalized_coverage) if normalized_coverage else 0,
        }
    
    def generate_llm_coverage_format(self) -> Dict[str, List[str]]:
        """
        Generate LLM output in the same format as Defects4J method_coverage.

        If the LLM report already includes method_coverage JSON, reuse it.
        Otherwise, fall back to placeholder coverage.
        """
        try:
            content = Path(self.llm_report_path).read_text(encoding='utf-8')
        except FileNotFoundError:
            content = ""

        method_coverage = self._extract_method_coverage_json(content)
        if method_coverage:
            return method_coverage

        llm_coverage = {}
        for method in self.llm_methods:
            llm_coverage[method] = ["predicted|1"]

        return llm_coverage
    
    def generate_comparison_report(self, output_path: str = None) -> str:
        """
        Generate detailed comparison report
        """
        comparison = self.compare()
        
        report_lines = [
            "=" * 80,
            "LLM EXECUTION PATH vs DEFECTS4J COVERAGE COMPARISON",
            "=" * 80,
            "",
            f"Coverage file: {self.defects4j_json_path}",
            f"LLM report: {self.llm_report_path}",
            "",
            "=" * 80,
            "SUMMARY STATISTICS",
            "=" * 80,
            "",
            f"Ground Truth (Coverage) Methods: {comparison['total_coverage_methods']}",
            f"LLM Predicted Methods: {comparison['total_llm_methods']}",
            f"Exact Matches: {len(comparison['exact_matches'])}",
            f"Normalized Matches: {comparison['normalized_matches']}",
            "",
            f"Exact Precision: {comparison['exact_precision']:.2%}",
            f"Exact Recall: {comparison['exact_recall']:.2%}",
            f"Normalized Precision: {comparison['normalized_precision']:.2%}",
            f"Normalized Recall: {comparison['normalized_recall']:.2%}",
            "",
        ]
        
        # Exact matches
        if comparison['exact_matches']:
            report_lines.extend([
                "=" * 80,
                f"EXACT MATCHES ({len(comparison['exact_matches'])})",
                "=" * 80,
                ""
            ])
            for i, method in enumerate(comparison['exact_matches'][:20], 1):
                report_lines.append(f"{i}. {method}")
            if len(comparison['exact_matches']) > 20:
                report_lines.append(f"... and {len(comparison['exact_matches']) - 20} more")
            report_lines.append("")
        
        # Missing methods
        if comparison['missing_methods']:
            report_lines.extend([
                "=" * 80,
                f"MISSING METHODS ({len(comparison['missing_methods'])})",
                "=" * 80,
                "(In coverage but NOT predicted by LLM)",
                ""
            ])
            for i, method in enumerate(comparison['missing_methods'][:30], 1):
                # Show line count from coverage
                line_count = len(self.coverage_methods.get(method, []))
                report_lines.append(f"{i}. {method} [{line_count} lines]")
            if len(comparison['missing_methods']) > 30:
                report_lines.append(f"... and {len(comparison['missing_methods']) - 30} more")
            report_lines.append("")
        
        # Extra methods
        if comparison['extra_methods']:
            report_lines.extend([
                "=" * 80,
                f"EXTRA METHODS ({len(comparison['extra_methods'])})",
                "=" * 80,
                "(Predicted by LLM but NOT in coverage)",
                ""
            ])
            for i, method in enumerate(comparison['extra_methods'][:30], 1):
                report_lines.append(f"{i}. {method}")
            if len(comparison['extra_methods']) > 30:
                report_lines.append(f"... and {len(comparison['extra_methods']) - 30} more")
            report_lines.append("")
        
        report = "\n".join(report_lines)
        
        # Save to file if path provided
        if output_path:
            Path(output_path).write_text(report, encoding='utf-8')
            print(f"✓ Comparison report saved to: {output_path}")
        
        return report
    
    def export_llm_coverage_json(self, output_path: str):
        """
        Export LLM predictions in the same JSON format as Defects4J
        """
        llm_coverage = self.generate_llm_coverage_format()
        
        output = {
            "metadata": {
                "source": "LLM Execution Path Prediction",
                "llm_report": self.llm_report_path,
                "total_methods": len(llm_coverage)
            },
            "method_coverage": llm_coverage
        }
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"✓ LLM coverage JSON saved to: {output_path}")


def main():
    """Example usage"""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python coverage_comparator.py <defects4j_json> <llm_report> [bug_id] [--compare-by-name]")
        print("\nExample:")
        print("  python coverage_comparator.py Math_All_Bugs_Fixed.json langgraph_analysis_20260217_140235.txt 5")
        print("  python coverage_comparator.py Math_All_Bugs_Fixed.json langgraph_analysis_20260219_094004.txt 10 --compare-by-name")
        sys.exit(1)

    defects4j_json = sys.argv[1]
    llm_report = sys.argv[2]
    bug_id = None
    compare_by_name = False

    for arg in sys.argv[3:]:
        if arg == "--compare-by-name":
            compare_by_name = True
        elif bug_id is None:
            bug_id = arg

    print("\n🔍 Starting Coverage Comparison...")
    print("=" * 80)

    comparator = CoverageComparator(defects4j_json, llm_report)

    # Load data
    comparator.load_defects4j_coverage(bug_id)
    comparator.load_llm_report()

    output_dir = Path(llm_report).parent
    timestamp = Path(llm_report).stem.split('_')[-2:]

    if compare_by_name:
        report = comparator.compare_by_method_name(bug_id)
        report_path = output_dir / f"comparison_by_name_{'_'.join(timestamp)}.json"
        Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"✓ Method-name comparison saved to: {report_path}")
    else:
        # Generate comparison
        report = comparator.generate_comparison_report()
        print(report)

        # Save reports
        report_path = output_dir / f"comparison_report_{'_'.join(timestamp)}.txt"
        json_path = output_dir / f"llm_coverage_{'_'.join(timestamp)}.json"

        comparator.generate_comparison_report(str(report_path))
        comparator.export_llm_coverage_json(str(json_path))

    print("\n✓ Comparison complete!")


if __name__ == "__main__":
    main()
