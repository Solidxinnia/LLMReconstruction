import json
import re
import time
import os
from typing import List, Dict, Any, TypedDict, Optional, Tuple
from pathlib import Path
from datetime import datetime
import sys

def _apply_mutation(body: str, line_no: int, original: str, mutated: str) -> str:
    """Apply a single-line mutation to the method body (0-based line index)."""
    if not body:
        return body

    lines = body.splitlines()
    if line_no < 0 or line_no >= len(lines):
        return body

    if original and original in lines[line_no]:
        lines[line_no] = lines[line_no].replace(original, mutated, 1)
    else:
        lines[line_no] = f"{lines[line_no]}  // MUTATION: {mutated}"

    return "\n".join(lines)


def _with_line_numbers(code: str) -> str:
    """Prefix code with 1-based line numbers for reliable coverage mapping.
    
    CRITICAL: Strip leading/trailing blank lines from callgraph JSON to prevent line drift.
    The callgraph JSON method bodies often have extra whitespace that causes misalignment
    with ground truth line numbers.
    """
    if not code:
        return code
    
    # Strip leading and trailing blank lines to match ground truth numbering
    lines = code.splitlines()
    
    # Find first non-blank line
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip():
            start_idx = i
            break
    
    # Find last non-blank line
    end_idx = len(lines) - 1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            end_idx = i
            break
    
    # Extract non-blank range
    lines = lines[start_idx:end_idx + 1]
    
    width = max(2, len(str(max(0, len(lines) - 1))))
    return "\n".join(f"{i:>{width}}: {line}" for i, line in enumerate(lines, start=0))

def get_production_method_body(
    method_name: str,
    mutation_id: str
) -> str:
    """Get method body from callgraph"""
    with open('data/raw/Math-5b_methods.json', 'r', encoding='utf-8') as f:
            callgraph = json.load(f)
    method_bodies = callgraph['method_bodies']
    mutation_index = callgraph.get('mutations', {})

    # GUARDRAIL: Reject ambiguous method names (require fully-qualified signatures)
    if method_name and ':' in method_name:
        class_part = method_name.split(':')[0]
        # Check if it looks like a bare class name without package
        if '.' not in class_part and not class_part.startswith('('):
            return (
                f"⚠️ AMBIGUOUS METHOD NAME: '{method_name}'\n"
                f"Please use FULLY-QUALIFIED signature with package:\n"
                f"  ✗ WRONG: '{method_name}'\n"
                f"  ✓ CORRECT: 'org.apache.commons.math3.analysis.function.{method_name}'\n"
                f"Fully-qualified names prevent ambiguity (e.g., multiple classes with same method name)."
            )

    # Check if this is a built-in Java method
    if is_builtin_method(method_name):
        return (
            f"⚠️ '{method_name}' is a Java standard library (built-in) method.\n"
            f"Built-in methods are part of the JDK and not included in this callgraph.\n"
            f"You should focus on Apache Commons Math3 methods instead.\n"
            f"Examples: org.apache.commons.math3.*, not java.lang.* or java.util.*"
        )

    # Try exact match first
    if method_name in method_bodies:
        body = method_bodies[method_name]
        if mutation_id:
            mutation = mutation_index.get(method_name, {}).get(mutation_id)
            if mutation:
                body = _apply_mutation(body, mutation["line"], mutation["original"], mutation["mutated"])
        numbered_body = _with_line_numbers(body)
        return f"Method: {method_name}\n{numbered_body}\n"

    # Try partial match
    matches = []
    method_lower = method_name.lower()
    for sig, body in method_bodies.items():
        if method_lower in sig.lower():
            if mutation_id:
                mutation = mutation_index.get(sig, {}).get(mutation_id)
                if mutation:
                    body = _apply_mutation(body, mutation["line"], mutation["original"], mutation["mutated"])
            matches.append(f"Method: {sig}\n{_with_line_numbers(body)}\n")

    if matches:
        return "\n\n".join(matches[:2])

    available = list(method_bodies.keys())[:5]
    return f"No method body found for '{method_name}'. Ask from available: {', '.join(available)}"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 get_mutated_code.py <method_name> <mutation_id>")
    else:
        get_production_method_body(sys.argv[1], sys.argv[2])


