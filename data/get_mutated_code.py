import json
import re
import os
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
    """Prefix code with 0-based line numbers.
    Strips leading/trailing blank lines as requested.
    """
    if not code:
        return code
    
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

def get_production_method_body(method_name: str, mutation_id: str) -> str:
    """Extracts and optionally mutates the method from Math-7b_methods.json"""
    json_path = 'data/raw/Math-7b_methods.json'
    
    if not os.path.exists(json_path):
        return f"Error: {json_path} not found."

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Access the list under the "Math-7b" key
    entries = data.get("Math-7b", [])
    
    # Search for the specific method
    for entry in entries:
        if entry.get("method") == method_name:
            body = entry.get("body", "")
            
            # Check for mutation within this method
            mutations = entry.get("mutation", [])
            for mut_str in mutations:
                if mutation_id in mut_str:
                    # Parse: ID:Line:Original |==> Mutated
                    match = re.match(r"^(?P<id>[^:]+):(?P<line>\d+):(?P<orig>.*?)\s*\|?==>\s*(?P<mut>.*)$", mut_str)
                    if match:
                        line_idx = int(match.group('line'))
                        orig_code = match.group('orig').strip()
                        mut_code = match.group('mut').strip()
                        body = _apply_mutation(body, line_idx, orig_code, mut_code)
                        break # Found the specific mutation for this method
            
            numbered_body = _with_line_numbers(body)
            return f"Method: {method_name}\n{numbered_body}\n"

    return f"No method body found for '{method_name}' with ID '{mutation_id}'."

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 get_mutated_code.py <method_name> <mutation_id>")
    else:
        # Example call: python3 get_mutated_code.py "org.apache...Complex:equals(java.lang.Object)" "Math-5_5_22_288"
        print(get_production_method_body(sys.argv[1], sys.argv[2]))