#!/usr/bin/env python3
"""
Apache Commons Math3 Execution Path Analyzer with LangGraph

A graph-based orchestrator using LangGraph to analyze test suites and callgraph
to determine execution paths in the Apache Commons Math3 project.
"""

import json
import re
import time
import os
from typing import List, Dict, Any, TypedDict
from pathlib import Path
from datetime import datetime
import requests

# LangGraph imports
from langgraph.graph import StateGraph, END

# LangSmith tracing (optional - only if LANGCHAIN_API_KEY is set)
LANGSMITH_ENABLED = False
langsmith_client = None

if os.environ.get("LANGCHAIN_API_KEY"):
    try:
        from langsmith import Client, traceable
        from langsmith.run_helpers import trace

        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.environ.get("LANGCHAIN_PROJECT", "Apache-Math3-Analysis")

        langsmith_client = Client()
        LANGSMITH_ENABLED = True
        print("✓ LangSmith tracing enabled")
        print(f"  Project: {os.environ['LANGCHAIN_PROJECT']}")
        print(f"  Dashboard: https://smith.langchain.com/projects")
    except ImportError:
        print("⚠️  langsmith package not found - install with: pip install langsmith")
        print("ℹ️  LangSmith tracing disabled")
    except Exception as e:
        print(f"⚠️  LangSmith initialization failed: {e}")
        print("ℹ️  LangSmith tracing disabled")
else:
    print("ℹ️  LangSmith tracing disabled (set LANGCHAIN_API_KEY to enable)")


# ============================================================
# STATE DEFINITION
# ============================================================

class AnalysisState(TypedDict):
    """State object passed through the graph"""

    # Configuration
    callgraph_csv: str
    tests_root: str
    output_dir: str
    max_iterations: int
    test_name: str  # The specific test to analyze

    # Data loaded from disk
    callgraph: Dict[str, Any]
    tests: List[Dict[str, str]]

    # Analysis state
    iteration: int
    current_understanding: str
    lines_to_execute: List[str]
    method_coverage: Dict[str, List[str]]
    needs_line_coverage: bool
    tool_requests: List[Dict[str, Any]]  # Current iteration tool requests

    # Tool execution tracking
    tool_history: List[Dict[str, Any]]  # Manually managed list (no auto-append)
    consecutive_duplicates: int

    # LLM interaction
    messages: List[Any]  # Chat history (managed manually)
    llm_response: str  # Current LLM response

    # Status
    done: bool
    error: str


# ============================================================
# MLX CLIENT
# ============================================================

class MLXClient:
    """Simple MLX server client"""

    def __init__(self, base_url: str = "http://localhost:8080/v1",
                 model: str = "mlx-community/gemma-3-12b-it-4bit",
                 max_tokens: int = 16384,  # Reduced to prevent memory overflow
                 temperature: float = 0.1,
                 timeout: float = 720.0):
        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def test_connection(self) -> bool:
        """Test if MLX server is reachable"""
        try:
            resp = requests.get(f"{self.base_url}/models", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def call(self, messages: List[Dict[str, str]]) -> str:
        """Call MLX chat/completions endpoint"""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return f"Error: {resp.status_code} - {resp.text[:120]}"
        except requests.exceptions.Timeout:
            return "Error: Request timeout"
        except Exception as e:
            return f"Error: {str(e)}"


# ============================================================
# TOOL FUNCTIONS
# ============================================================

def load_callgraph(csv_path: str) -> Dict[str, Any]:
    """Load callgraph from CSV"""
    import csv

    relationships = []
    method_bodies = {}

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                caller = row.get('caller', '')
                callee = row.get('callee', '')
                caller_body = row.get('caller_body', '')
                callee_body = row.get('callee_body', '')

                relationships.append({
                    'caller': caller,
                    'callee': callee
                })

                if caller and caller_body and caller_body != 'BODY_NOT_FOUND':
                    method_bodies[caller] = caller_body
                if callee and callee_body and callee_body != 'BODY_NOT_FOUND':
                    method_bodies[callee] = callee_body

        print(f"✓ Loaded callgraph: {len(relationships)} relationships, {len(method_bodies)} method bodies")
        return {
            'relationships': relationships,
            'method_bodies': method_bodies
        }
    except Exception as e:
        print(f"✗ Error loading callgraph: {e}")
        return {'relationships': [], 'method_bodies': {}}


def discover_tests(tests_root: str) -> List[Dict[str, str]]:
    """Discover test files across the full Apache Math3 test suite"""
    tests = []
    root = Path(tests_root)

    if not root.exists():
        print(f"✗ Test directory not found: {tests_root}")
        return tests

    for java_file in root.rglob("*.java"):
        try:
            content = java_file.read_text(encoding='utf-8', errors='ignore')
            if "@Test" in content or "test" in java_file.name.lower():
                tests.append({
                    'file': str(java_file.relative_to(root)),
                    'path': str(java_file),
                    'content': content
                })
        except Exception:
            continue

    print(f"✓ Discovered {len(tests)} test files")
    return tests


def get_callgraph_summary(callgraph: Dict[str, Any]) -> str:
    """Get summary of callgraph relationships"""
    relationships = callgraph['relationships']
    if not relationships:
        return "No callgraph relationships found"

    lines = ["Production Code Callgraph:"]
    for rel in relationships[:10]:
        lines.append(f"  {rel['caller']} → {rel['callee']}")

    if len(relationships) > 10:
        lines.append(f"  ...and {len(relationships) - 10} more relationships")

    return "\n".join(lines)


def get_production_method_body(callgraph: Dict[str, Any], method_name: str) -> str:
    """Get method body from callgraph"""
    method_bodies = callgraph['method_bodies']

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
        numbered_body = _with_line_numbers(method_bodies[method_name])
        return f"Method: {method_name}\n{numbered_body}\n"

    # Try partial match
    matches = []
    method_lower = method_name.lower()
    for sig, body in method_bodies.items():
        if method_lower in sig.lower():
            matches.append(f"Method: {sig}\n{_with_line_numbers(body)}\n")

    if matches:
        return "\n\n".join(matches[:2])

    available = list(method_bodies.keys())[:5]
    return f"No method body found for '{method_name}'. Ask from available: {', '.join(available)}"


def is_builtin_method(method_signature: str) -> bool:
    """Check if a method is from Java standard library (built-in)"""
    builtin_prefixes = [
        'java.lang.',
        'java.util.',
        'java.io.',
        'java.math.',
        'java.nio.',
        'java.text.',
        'java.net.',
        'javax.',
        '(S)java.lang.',  # Static calls
        '(S)java.util.',
        '(S)java.math.',
        '(S)java.io.',
        '(I)java.lang.',  # Interface calls
        '(I)java.util.',
        '(O)java.lang.',  # Object calls
        '(O)java.util.',
        '(O)java.io.',
        '(O)java.math.',
    ]
    return any(method_signature.startswith(prefix) for prefix in builtin_prefixes)


def _extract_method_body(source_code: str, method_name: str) -> str:
    """Extract a Java method body by name from a source file"""
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
            return source_code[start_index:i+1]

    return ""


def _with_line_numbers(code: str) -> str:
    """Prefix code with 1-based line numbers for reliable coverage mapping.
    
    CRITICAL: Strip leading/trailing blank lines from callgraph CSV to prevent line drift.
    The callgraph CSV method bodies often have extra whitespace that causes misalignment
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
    
    width = max(2, len(str(len(lines))))
    return "\n".join(f"{i:>{width}}: {line}" for i, line in enumerate(lines, start=1))


def get_test_method_body(tests: List[Dict[str, str]], method_name: str) -> str:
    """Get test method body by fully-qualified name (org.apache.commons.math3.package.Class.method)
    
    Args:
        tests: List of test file dictionaries
        method_name: Fully-qualified test method name like 'org.apache.commons.math3.analysis.solvers.LaguerreSolverTest.testQuinticFunction'
                    OR simple method name like 'testQuinticFunction' (will search all files)
    """
    if not method_name:
        return "Test method name is required"

    # Check if it's a fully-qualified name (contains dots and looks like package.Class.method)
    if '.' in method_name and method_name.count('.') >= 2:
        # Extract package path and method name
        # Example: org.apache.commons.math3.analysis.solvers.LaguerreSolverTest.testQuinticFunction
        # -> path: org/apache/commons/math3/analysis/solvers/LaguerreSolverTest
        # -> method: testQuinticFunction
        parts = method_name.split('.')
        simple_method = parts[-1]  # Last part is the method name
        class_name = parts[-2]  # Second to last is the class name
        
        # Construct expected file path: java/org/apache/commons/math3/.../ClassName.java
        # The file path in tests list looks like: java/org/apache/.../ClassName.java
        expected_path_suffix = '/'.join(parts[:-1]) + '.java'
        
        # Search for the specific test file matching the package path
        for test in tests:
            test_file = test.get('file', '')
            # Check if this test file matches the expected path
            if expected_path_suffix in test_file or test_file.endswith(f"{class_name}.java"):
                source_code = test.get('content', '')
                method_body = _extract_method_body(source_code, simple_method)
                if method_body:
                    return (
                        f"Test file: {test['file']}\n"
                        f"Test method: {simple_method} (from {method_name})\n"
                        f"\n{_with_line_numbers(method_body)}\n"
                    )
        
        return f"Test method '{method_name}' not found. Verify the fully-qualified name is correct."
    
    # Fallback: simple method name search (original behavior)
    matches = []
    for test in tests:
        source_code = test.get('content', '')
        method_body = _extract_method_body(source_code, method_name)
        if method_body:
            matches.append({
                'file': test['file'],
                'body': method_body
            })
    
    if not matches:
        return f"Test method '{method_name}' not found in any test file"
    
    if len(matches) == 1:
        return (
            f"Test file: {matches[0]['file']}\n"
            f"Test method: {method_name}\n"
            f"\n{_with_line_numbers(matches[0]['body'])}\n"
        )
    
    # Multiple matches found - return warning with all locations
    result = f"⚠️ AMBIGUOUS: Found {len(matches)} test methods named '{method_name}':\n\n"
    for i, match in enumerate(matches[:3], 1):
        result += f"{i}. {match['file']}\n"
    result += f"\nPlease use FULLY-QUALIFIED name like:\n"
    result += f"  'org.apache.commons.math3.package.ClassName.{method_name}'\n"
    return result


def get_all_tests(tests: List[Dict[str, str]]) -> str:
    """List all test files"""
    if not tests:
        return "No tests found"

    lines = [f"Total tests discovered: {len(tests)}"]
    for test in tests:
        lines.append(f"- {test['file']}")

    return "\n".join(lines)


def execute_tool(state: AnalysisState, tool_type: str, args: Dict[str, Any]) -> str:
    """Execute a tool request"""
    if tool_type == "get_callgraph":
        return get_callgraph_summary(state['callgraph'])
    if tool_type == "get_production_method_body":
        method_name = args.get("method_name", "")
        return get_production_method_body(state['callgraph'], method_name)
    if tool_type == "get_test_method_body":
        method_name = args.get("method_name", args.get("filename", ""))
        return get_test_method_body(state['tests'], method_name)
    if tool_type == "get_all_tests":
        return get_all_tests(state['tests'])
    return f"Unknown tool: {tool_type}"


def check_duplicate(state: AnalysisState, tool_type: str, args: Dict[str, Any]) -> str:
    """Check if tool was already called with same args"""
    request_key = f"{tool_type}|{json.dumps(args, sort_keys=True)}"

    for entry in state['tool_history']:
        req = entry.get('request', {})
        prev_key = f"{req.get('type')}|{json.dumps(req.get('args', {}), sort_keys=True)}"
        if request_key == prev_key:
            return entry.get('result', '')

    return None


# ============================================================
# GRAPH NODES
# ============================================================

def initialize_node(state: AnalysisState) -> AnalysisState:
    """Initialize the analysis"""
    print("\n" + "="*60)
    print("Apache Math3 Execution Path Analysis (LangGraph)")
    print("="*60)
    print(f"Callgraph: {state['callgraph_csv']}")
    print(f"Tests: {state['tests_root']}")
    print(f"Max iterations: {state['max_iterations']}")
    print("="*60 + "\n")

    # Test MLX connection
    client = MLXClient()
    if not client.test_connection():
        print("✗ Cannot connect to MLX server")
        state['done'] = True
        state['error'] = "MLX server not reachable"
        return state

    print("✓ MLX server connected\n")

    # Load data
    state['callgraph'] = load_callgraph(state['callgraph_csv'])
    state['tests'] = discover_tests(state['tests_root'])

    # Initialize state
    state['iteration'] = 0
    state['current_understanding'] = "Starting analysis..."
    state['lines_to_execute'] = []
    state['method_coverage'] = {}
    state['needs_line_coverage'] = False
    state['tool_requests'] = []
    state['tool_history'] = []
    state['consecutive_duplicates'] = 0
    state['messages'] = []
    state['llm_response'] = ""
    state['done'] = False
    state['error'] = ""

    return state


def build_prompt_node(state: AnalysisState) -> AnalysisState:
    """Build prompt for LLM"""
    iteration = state['iteration']

    # Build tool history - DEDUPLICATE to keep only LATEST result for each tool+args
    tools_called = {}
    for entry in state['tool_history']:
        req = entry.get('request', {})
        tool_type = req.get('type', 'unknown')
        args = req.get('args', {})

        # Create unique key for this tool+args combination
        key = f"{tool_type}:{json.dumps(args, sort_keys=True)}"

        # Only keep the LATEST result for each unique tool call
        tools_called[key] = {
            'tool_type': tool_type,
            'args': args,
            'result': entry.get('result', '')[:400]
        }

    tool_history = "=" * 60 + "\n"
    tool_history += "INFORMATION YOU ALREADY RETRIEVED (DO NOT REQUEST AGAIN):\n"
    tool_history += "=" * 60 + "\n"

    if tools_called:
        # Group by tool type for display
        by_type = {}
        for key, data in tools_called.items():
            tool_type = data['tool_type']
            if tool_type not in by_type:
                by_type[tool_type] = []
            by_type[tool_type].append(data)

        for tool_type, calls in by_type.items():
            tool_history += f"\n✓✓✓ {tool_type.upper()} - ALREADY CALLED {len(calls)} TIME(S)\n"
            for idx, call in enumerate(calls, 1):
                tool_history += f"\n  Call #{idx}:\n"
                tool_history += f"  Args: {call['args']}\n"
                tool_history += "  Result (USE THIS DATA):\n"
                tool_history += f"  {call['result']}\n"
                tool_history += f"  {'-' * 50}\n"
    else:
        tool_history += "\nNone yet - this is your first request.\n"

    tool_history += "\n" + "=" * 60 + "\n"

    prompt_preview = f"""ITERATION: {iteration + 1}

YOUR CURRENT UNDERSTANDING:
{state['current_understanding']}

{tool_history}

what tools do you need next?

YOUR PROPOSED EXECUTION PATH SO FAR:
{', '.join(state['lines_to_execute']) if state['lines_to_execute'] else 'None yet'}

What do you need next? (If you have test body + method bodies, ANALYZE them instead of requesting again!)"""

    print(f"📊 Tool history entries: {len(state['tool_history'])}")
    print(f"📊 Prompt size: {len(prompt_preview):,} chars (~{len(prompt_preview)//4:,} tokens)")

    prompt = prompt_preview
    
    # Get the test name from state
    test_name = state.get('test_name', 'UNKNOWN_TEST')

    system_prompt = """SUMMARY: Autonomous Execution Path Analysis
PRIORITY: Critical
ROLE: Senior Java Software Engineering Agent

OBJECTIVE: Determine the execution path for test: '""" + test_name + """'. Identify every method call triggered by the test by requesting tools. For each method, determine which lines execute based on the specific argument values used in this test. Focus on line-level coverage, not just method names. Only include lines that actually execute with these argument values.

AVAILABLE TOOLS:
- get_callgraph(): Summarizes caller -> callee relationships
- get_production_method_body(method_name): Get production method definition (use FULLY-QUALIFIED names)
- get_test_method_body(method_name): Get test method definition (use FULLY-QUALIFIED name: 'org.apache.commons.math3.package.ClassName.methodName')
- get_all_tests(): List all test methods

TOOL USAGE EXAMPLES:
✓ get_test_method_body({"method_name": "org.apache.commons.math3.analysis.solvers.LaguerreSolverTest.testQuinticFunction"})  // Fully-qualified for tests
✓ get_production_method_body({"method_name": "org.apache.commons.math3.analysis.function.Sin:value"})  // Fully-qualified for production (note: use : for methods)

WORKFLOW:
Step 1: Get the test method body using its FULLY-QUALIFIED name.
Step 2: Identify all production methods called by the test.
CRITICAL: Assertion methods may have IMPLICIT calls that you must trace:
- Assert.assertEquals(a, b) internally calls a.equals(b) or b.equals(a) for object comparisons. Always trace .equals() when you see assertEquals() with objects.
- Assert.assertTrue(condition) evaluates the condition but does not call other methods.
- Assert.assertSame(a, b) uses == comparison (no method calls).
Step 3: For each production method discovered:
a) Get its body using the FULLY-QUALIFIED name (e.g., org.apache.commons.math3.analysis.complex.Sin:value).
b) TRACE ARGUMENT VALUES from the test to determine which branches execute:
- If the test calls reciprocal() on Complex.ZERO, then real = 0.0 and imaginary = 0.0.
- If the test calls method(5), then the parameter value is 5.
- Use these known values to evaluate conditions such as if (real == 0.0 && imaginary == 0.0) → TRUE.
- Only include lines that ACTUALLY EXECUTE for these specific argument values.
c) Perform LINE-BY-LINE execution analysis based on argument values and record coverage:
- Output line-level coverage in method_coverage with actual line numbers.
- For every conditional line (if/else, switch, ternary ?:, ||, &&), add branch coverage using the format:
"lineNumber|hitCount|percentage% (covered/total)".
- Determine total branches and covered branches using argument evaluation:
1. if (condition) → 2 branches (true, false)
2. if (a && b) → 4 branches (both true; a true b false; a false b true; both false)
3. if (a || b) → 4 branches (both true; a true b false; a false b true; both false)
4. condition ? x : y → 2 branches (true → x, false → y)
- Calculate percentage as:
(covered / total) * 100%
- Examples:
1. "5|1|50% (1/2)" → line 5, hit once, 1 of 2 branches covered (50%)
2. "10|2|25% (1/4)" → line 10, hit twice, 1 of 4 branches covered (25%)
3. "15|11|100% (2/2)" → line 15, hit eleven times, both branches covered (100%)
d) Check whether the method returns a wrapper, factory, or anonymous class.
e) If yes, trace the methods of the returned object.
f) Check for method overloads (different parameter types).
g) Follow derivative chains or similar call patterns.
Step 4: Build the complete execution path with LINE-LEVEL and BRANCH COVERAGE for all discovered methods.
Step 5: Mark done=true ONLY when you have line-level AND branch coverage for ALL methods (not just method names!).

EXAMPLE WITH ARGUMENT TRACING:
Test: Complex.ZERO.reciprocal() where Complex.ZERO has real=0.0, imaginary=0.0

Method body:
 1: public Complex reciprocal() {
 2:     if (isNaN) {                                // 2 branches: true/false
 3:         return NaN;
 4:     }
 5:     if (real == 0.0 && imaginary == 0.0) {     // 4 branches: TT/TF/FT/FF
 6:         return INF;  // This line executes
 7:     }
 8:     if (isInfinite) {                           // This line does NOT execute (already returned)
 9:         return ZERO;
10:     }

Reasoning: "Test calls Complex.ZERO.reciprocal(). Complex.ZERO has real=0.0 and imaginary=0.0. 
In reciprocal(), line 2 checks isNaN (false for ZERO), so only the false branch executes (1/2 branches).
Line 5 checks if (real == 0.0 && imaginary == 0.0) which is TRUE (both conditions true, so 1/4 branches covered).
Line 6 executes and returns INF. Lines 8+ don't execute because we already returned."

Output: 
[
    "1|1|50% (1/2)",      // Line 1: method signature with implicit return branch (normal/exception)
    "2|1|50% (1/2)",      // Line 2: if (isNaN) - only false branch executes
    "5|1|25% (1/4)",      // Line 5: if (real == 0.0 && imaginary == 0.0) - only TT branch executes
    "6|1"                 // Line 6: return statement (no branches)
]  

RESPONSE FORMAT (JSON):
{
    "reasoning": "What you learned from tool calls. Decide which methods execute and which lines within those methods. Explain your reasoning for which lines execute based on the test and method bodies.",
    "method_coverage": {
        "fully.qualified.ClassName:methodName(params)": [
            "lineNumber|hitCount",
            "lineNumber|hitCount|condition% (covered/total)"
        ]
    },
    "requests": [
        {"type": "tool_name", "args": {"key": "value"}}
    ],
    "done": false
}

EXAMPLE OUTPUT:
{
    "reasoning": "The test org.apache.commons.math3.complex.ComplexTest.testScalarDivideNaN creates x = new Complex(3.0, 4.0) (so isNaN = false) and a divisor equal to Double.NaN. It then compares x.divide(new Complex(Double.NaN)) and x.divide(Double.NaN). In divide(Complex divisor), line 2 checks if (isNaN || divisor.isNaN). For x, isNaN is false, but for the divisor (new Complex(Double.NaN)), isNaN is true, so the condition is TRUE (1/2 branches covered), and the method immediately returns Complex.NaN. The subsequent checks for (c == 0.0 && d == 0.0), divisor.isInfinite(), and the magnitude comparison branches do not execute because of the early return. In divide(double divisor), line 2 checks if (isNaN || Double.isNaN(divisor)). Since Double.isNaN(NaN) is true, this condition is also TRUE (1/2 branches covered), and the method immediately returns Complex.NaN",
    "method_coverage": {
        "org.apache.commons.math3.analysis.FunctionUtils:toUnivariateDifferential": [
            "6645|1",
            "6646|1",
            "6651|1|50% (1/2)",
            "6654|1"
        ],
        "org.apache.commons.math3.analysis.function.Sin:value(double)": [
            "23817|1"
        ],
        "org.apache.commons.math3.analysis.function.Sin:derivative()": [
            "23874|1"
        ],
        "org.apache.commons.math3.analysis.function.Cos:value(double)": [
            "21963|1"
        ]
    },
    "requests": [],
    "done": true
}

"""

    # Create FRESH messages each iteration (stateless)
    state['messages'] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    return state


def llm_call_node(state: AnalysisState) -> AnalysisState:
    """Call LLM"""
    print(f"\n[ITERATION {state['iteration'] + 1}/{state['max_iterations']}]" )

    total_chars = sum(len(msg.get('content', '')) for msg in state['messages'])
    approx_tokens = total_chars // 4
    print(f"📊 Message history: {len(state['messages'])} messages, ~{approx_tokens:,} tokens (~{total_chars:,} chars)")

    if approx_tokens > 16000:
        print("⚠️  WARNING: Token count is high! May cause memory issues.")

    print("Calling LLM...")

    client = MLXClient()
    start_time = time.time()
    response = client.call(state['messages'])
    elapsed = time.time() - start_time

    if response.startswith("Error:"):
        print(f"✗ LLM error: {response}")
        state['done'] = True
        state['error'] = response
        return state

    print(f"✓ Response received in {elapsed:.1f}s ({len(response)} chars)")

    state['llm_response'] = response

    return state


def parse_response_node(state: AnalysisState) -> AnalysisState:
    """Parse LLM response"""
    response = state['llm_response']

    def _is_line_entry(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        line = value.strip()
        return bool(re.match(r"^\d+\|\d+(\|\d+% \(\d+/\d+\))?$", line))

    # Handle markdown code blocks
    if "```json" in response:
        response = response.split("```json")[-1].split("```")[0]

    # Extract JSON
    json_match = re.search(r'\{.*\}', response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))

            # Update state
            reasoning = data.get("reasoning", response.strip())
            state['current_understanding'] = reasoning

            # Support method_coverage (preferred) and legacy fields
            method_coverage = data.get("method_coverage")
            if isinstance(method_coverage, dict):
                lines = list(method_coverage.keys())
                state['method_coverage'] = method_coverage
            else:
                lines = data.get("execution_path", data.get("lines_to_execute", []))
                state['method_coverage'] = {}

            if lines:
                state['lines_to_execute'].extend(lines)

            state['tool_requests'] = data.get("requests", [])
            state['done'] = data.get("done", False)
            state['needs_line_coverage'] = False

            # Enforce line-level coverage: auto-request method bodies if missing/invalid
            missing_methods = []
            if isinstance(method_coverage, dict):
                for method_name, covered_lines in method_coverage.items():
                    if not isinstance(covered_lines, list) or not covered_lines:
                        missing_methods.append(method_name)
                        continue
                    if any(not _is_line_entry(entry) for entry in covered_lines):
                        missing_methods.append(method_name)
            elif lines:
                # Legacy outputs: treat lines as method names needing coverage
                missing_methods.extend([line for line in lines if isinstance(line, str) and line.strip()])

            if missing_methods:
                state['done'] = False
                state['needs_line_coverage'] = True
                warning = (
                    "\n\n⚠️ Missing line-level coverage. "
                    "Requesting method bodies so the next response can include line numbers."
                )
                state['current_understanding'] = (reasoning + warning).strip()
                existing_reqs = {
                    f"{req.get('type')}|{json.dumps(req.get('args', {}), sort_keys=True)}"
                    for req in state['tool_requests']
                }
                for method_name in sorted(set(missing_methods)):
                    req = {
                        "type": "get_production_method_body",
                        "args": {"method_name": method_name}
                    }
                    key = f"{req['type']}|{json.dumps(req['args'], sort_keys=True)}"
                    if key not in existing_reqs:
                        state['tool_requests'].append(req)
                        existing_reqs.add(key)

            print(f"\nReasoning: {reasoning}")
            if lines:
                print(f"Proposed execution path: {', '.join(lines[:3])}...")
            if state['tool_requests']:
                print(f"Tool requests: {len(state['tool_requests'])}")

            return state
        except json.JSONDecodeError as e:
            print(f"✗ JSON parse error: {e}")
            print(f"Response preview: {response[:200]}")
    else:
        print("✗ No JSON found in response")
        print(f"Response preview: {response[:200]}")

    # Fallback
    state['current_understanding'] = response.strip()
    state['tool_requests'] = []
    print("⚠ No tool requests found - using fallback")

    return state


def execute_tools_node(state: AnalysisState) -> AnalysisState:
    """Execute tool requests"""
    requests_list = state.get('tool_requests', [])

    if not requests_list:
        print("⚠ No tool requests made")
        state['consecutive_duplicates'] += 1
        return state

    print(f"\nExecuting {len(requests_list)} tool request(s)...")
    all_duplicates = True

    for i, req in enumerate(requests_list):
        tool_type = req.get('type')
        args = req.get('args', {})

        print(f"  {i+1}. {tool_type}({args})")

        # Check for duplicate
        cached = check_duplicate(state, tool_type, args)
        if cached:
            result = f"[DUPLICATE] {cached}"
            print("     → 🔄 Using cached result")
        else:
            all_duplicates = False
            result = execute_tool(state, tool_type, args)
            print(f"     → {result[:100]}...")

        if 'tool_history' not in state or state['tool_history'] is None:
            state['tool_history'] = []

        state['tool_history'].append({
            'iteration': state['iteration'],
            'request': req,
            'result': result[:800]
        })

    return state


def check_completion_node(state: AnalysisState) -> AnalysisState:
    """Check if analysis should continue or end and update state"""
    if state.get('done', False):
        print("\n✓ Analysis marked complete by LLM!")
        return state

    if state['iteration'] >= state['max_iterations'] - 1:
        if state.get('needs_line_coverage', False):
            state['max_iterations'] += 3
            print(
                f"\n⚠ Extending max iterations to {state['max_iterations']} "
                "to finish line-level coverage."
            )
        else:
            print(f"\n⚠ Reached max iterations ({state['max_iterations']})")
            state['done'] = True
            return state

    if state['consecutive_duplicates'] >= 3:
        print("\n⚠⚠⚠ STOPPING: 3 consecutive iterations with only duplicate requests!")
        state['done'] = True
        return state

    state['iteration'] += 1
    return state


def should_continue(state: AnalysisState) -> str:
    """Router function to decide next step"""
    if state.get('done', False) or state.get('error'):
        return "complete"
    return "continue"


def generate_report_node(state: AnalysisState) -> AnalysisState:
    """Generate final report"""
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)
    print(f"Iterations: {state['iteration'] + 1}")
    print(f"Tool calls: {len(state.get('tool_history', []))}")
    print(f"Execution path identified: {len(state['lines_to_execute'])} methods/lines")

    state['done'] = True

    report = f"""Apache Math3 Execution Path Analysis Report (LangGraph)
Generated: {datetime.now().isoformat()}

{'='*60}
FINAL UNDERSTANDING
{'='*60}

{state['current_understanding']}

{'='*60}
EXECUTION PATH
{'='*60}

Methods/Lines to Execute:
"""
    if state['lines_to_execute']:
        for i, line in enumerate(state['lines_to_execute'], 1):
            report += f"{i}. {line}\n"
    else:
        report += "None identified\n"

    report += f"\n{'='*60}\nMETHOD COVERAGE (LINE-LEVEL)\n{'='*60}\n\n"
    if state.get('method_coverage'):
        report += json.dumps(state['method_coverage'], indent=2)
        report += "\n"
    else:
        report += "No method_coverage JSON produced.\n"

    report += f"\n{'='*60}\nTOOL EXECUTION HISTORY\n{'='*60}\n\n"

    tool_history_items = state.get('tool_history', [])
    if len(tool_history_items) > 10000:
        print(f"⚠️  WARNING: tool_history has {len(tool_history_items)} entries! Only showing first 100.")
        tool_history_items = tool_history_items[:100]

    for i, entry in enumerate(tool_history_items, 1):
        req = entry.get('request', {})
        result = entry.get('result', '')

        report += f"{i}. {req.get('type')}({req.get('args', {})})\n"
        report += f"   Result: {result[:300]}...\n\n"

    output_dir = Path(state['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"langgraph_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_path.write_text(report, encoding='utf-8')

    state['report_path'] = str(report_path)
    print(f"\n✓ Report saved to: {report_path}")
    print("✓ Graph execution complete - returning to main()")

    return state


# ============================================================
# BUILD GRAPH
# ============================================================

def build_graph() -> StateGraph:
    """Build the LangGraph workflow"""
    workflow = StateGraph(AnalysisState)

    # Add nodes
    workflow.add_node("initialize", initialize_node)
    workflow.add_node("build_prompt", build_prompt_node)
    workflow.add_node("llm_call", llm_call_node)
    workflow.add_node("parse_response", parse_response_node)
    workflow.add_node("execute_tools", execute_tools_node)
    workflow.add_node("check_completion", check_completion_node)
    workflow.add_node("generate_report", generate_report_node)

    # Set entry point
    workflow.set_entry_point("initialize")

    # Add edges
    workflow.add_edge("initialize", "build_prompt")
    workflow.add_edge("build_prompt", "llm_call")
    workflow.add_edge("llm_call", "parse_response")
    workflow.add_edge("parse_response", "execute_tools")
    workflow.add_edge("execute_tools", "check_completion")

    # Conditional edge based on completion check
    workflow.add_conditional_edges(
        "check_completion",
        should_continue,
        {
            "continue": "build_prompt",
            "complete": "generate_report"
        }
    )

    workflow.add_edge("generate_report", END)

    return workflow.compile()


# ============================================================
# MAIN
# ============================================================

def main():
    """Main entry point"""
    import sys
    
    print("Apache Math3 Execution Path Analyzer (LangGraph)")
    print("="*60)

    # Parse command line arguments
    if len(sys.argv) < 4:
        print("\nUsage: python3 main_apache_math3.py <callgraph_csv> <tests_root> <test_name>")
        print("\nExample:")
        print("  python3 main_apache_math3.py 'data/raw/callgraph2.csv' 'data/raw/test2' 'org.apache.commons.math3.util.MathArraysTest::testLinearCombinationWithSingleElementArray'")
        print("\nArguments:")
        print("  callgraph_csv : Path to the callgraph CSV file")
        print("  tests_root    : Path to the test directory")
        print("  test_name     : Fully qualified test name (use :: or . as separator)")
        print("\n")
        sys.exit(1)
    
    callgraph_csv = sys.argv[1]
    tests_root = sys.argv[2]
    test_name = sys.argv[3]
    
    # Convert :: to . for consistency
    test_name = test_name.replace('::', '.')
    
    # Derive output directory from callgraph path
    # e.g., callgraph2.csv -> reconstructions2
    import re
    match = re.search(r'callgraph(\d*)', callgraph_csv)
    suffix = match.group(1) if match else ''
    output_dir = f"data/outputs/reconstructions{suffix}"
    
    print(f"\nConfiguration:")
    print(f"  Callgraph: {callgraph_csv}")
    print(f"  Tests root: {tests_root}")
    print(f"  Test name: {test_name}")
    print(f"  Output dir: {output_dir}")
    print("="*60)

    # Configuration
    initial_state: AnalysisState = {
        "callgraph_csv": callgraph_csv,
        "tests_root": tests_root,
        "output_dir": output_dir,
        "max_iterations": 25,
        "test_name": test_name,  # Store test name in state

        # Will be populated
        "callgraph": {},
        "tests": [],
        "iteration": 0,
        "current_understanding": "",
        "llm_response": "",
        "lines_to_execute": [],
        "method_coverage": {},
        "needs_line_coverage": False,
        "tool_requests": [],
        "tool_history": [],
        "consecutive_duplicates": 0,
        "messages": [],
        "done": False,
        "error": ""
    }

    # Build and run graph
    try:
        graph = build_graph()

        print("\n🚀 Starting graph execution...")

        if LANGSMITH_ENABLED and langsmith_client:
            from langsmith.run_helpers import traceable

            @traceable(name="Apache-Math3-Analysis-Run", run_type="chain")
            def traced_invoke(state):
                return graph.invoke(state)

            print("📊 LangSmith: Creating trace...")
            final_state = traced_invoke(initial_state)
        else:
            final_state = graph.invoke(initial_state)

        print("✓ Graph.invoke() returned successfully")

        # Print results
        if final_state.get("error"):
            print(f"\n✗ Analysis failed: {final_state['error']}")
        else:
            print("\n" + "="*60)
            print("SUCCESS!")
            print("="*60)
            if final_state.get("lines_to_execute"):
                print("\nIdentified execution path:")
                for line in final_state["lines_to_execute"][:10]:
                    print(f"  - {line}")
            if final_state.get('report_path'):
                print(f"\nFull report: {final_state.get('report_path')}")

        print("\n✓ Main() completing - exiting normally")

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user (Ctrl+C)")
        import sys
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()