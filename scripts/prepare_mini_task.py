#!/usr/bin/env python3
"""Prepare a strict JSON-only mini-swe-agent task prompt.

Usage:
  python scripts/prepare_mini_task.py \
    --callgraph /path/to/Math-5b_methods.json \
    --tests-root /path/to/test/root \
    --test-name org.apache.commons.math3.complex.ComplexTest::testReciprocalZero \
    --output /tmp/mini_task.txt
"""

import argparse
import json
import re
from pathlib import Path


def _extract_method_body(source_code: str, method_name: str) -> str:
    pattern = rf"(?:public|protected|private|static|\s)+[\w\<\>\[\]]+\s+{method_name}\s*\([^\)]*\)\s*\{{"
    match = re.search(pattern, source_code)
    if not match:
        return ""
    start_index = match.start()
    brace_count = 0
    for i in range(match.end() - 1, len(source_code)):
        if source_code[i] == '{':
            brace_count += 1
        elif source_code[i] == '}':
            brace_count -= 1
        if brace_count == 0:
            return source_code[start_index:i + 1]
    return ""


def find_test_method_body(tests_root: Path, test_name: str) -> str:
    if "::" in test_name:
        test_name = test_name.replace("::", ".")
    parts = test_name.split(".")
    if len(parts) < 3:
        raise ValueError("Test name must be fully-qualified: package.Class.method")
    method = parts[-1]
    class_name = parts[-2]
    expected_suffix = "/".join(parts[:-1]) + ".java"

    for java_file in tests_root.rglob("*.java"):
        rel_path = str(java_file.relative_to(tests_root))
        if expected_suffix in rel_path or rel_path.endswith(f"{class_name}.java"):
            content = java_file.read_text(encoding="utf-8", errors="ignore")
            body = _extract_method_body(content, method)
            if body:
                return f"Test file: {rel_path}\nTest method: {method}\n\n{body}".strip()
    raise FileNotFoundError(f"Could not find test method body for {test_name}")


def load_method_bodies(callgraph_path: Path) -> dict:
    data = json.loads(callgraph_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        entries = data.get("methods") or data.get("data") or data.get("items")
        if entries is None:
            entries = next((value for value in data.values() if isinstance(value, list)), [])
    else:
        entries = data
    if not isinstance(entries, list):
        raise ValueError("Callgraph JSON must be a list of {method, body} entries")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        method_name = entry.get("method", "").strip()
        body = entry.get("body", "")
        if method_name and body and body != "BODY_NOT_FOUND":
            result[method_name] = body
    return result


def format_bodies(method_bodies: dict, prefix: str) -> str:
    lines = []
    for method, body in method_bodies.items():
        if method.startswith(prefix):
            lines.append(f"Method: {method}\n{body}\n")
    if not lines:
        return f"No production methods found for prefix: {prefix}"
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--callgraph", required=True)
    parser.add_argument("--tests-root", required=True)
    parser.add_argument("--test-name", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prefix", default="org.apache.commons.math3.complex.")
    args = parser.parse_args()

    tests_root = Path(args.tests_root)
    callgraph_path = Path(args.callgraph)

    test_body = find_test_method_body(tests_root, args.test_name)
    method_bodies = load_method_bodies(callgraph_path)
    production_body = format_bodies(method_bodies, args.prefix)

    template_path = Path(__file__).resolve().parents[1] / "prompts" / "mini_task_template.txt"
    template = template_path.read_text(encoding="utf-8")
    prompt = template.format(
        test_name=args.test_name.replace("::", "."),
        test_method_body=test_body,
        production_method_bodies=production_body,
    )

    output_path = Path(args.output)
    output_path.write_text(prompt, encoding="utf-8")
    print(f"Wrote mini task prompt to {output_path}")


if __name__ == "__main__":
    main()
