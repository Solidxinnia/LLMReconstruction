# Usage Guide for main_apache_math3.py

## Command-Line Arguments

The script now requires **3 command-line arguments**:

```bash
python3 main_apache_math3.py <callgraph_json> <tests_root> <test_name>
```

### Arguments

1. **`callgraph_json`** - Path to the callgraph JSON file
  - Example: `data/raw/callgraph.json`
  - Contains method bodies with fields `method` and `body`

2. **`tests_root`** - Path to the test directory root
   - Example: `data/raw/test2`
   - Directory containing Java test files

3. **`test_name`** - Fully qualified test method name
   - Example: `org.apache.commons.math3.util.MathArraysTest::testLinearCombinationWithSingleElementArray`
   - Can use `::` or `.` as separator (both work)
   - Format: `package.ClassName.methodName` or `package.ClassName::methodName`

## Example Usage

```bash
# Using :: separator
python3 main_apache_math3.py \
  'data/raw/callgraph.json' \
  'data/raw/test2' \
  'org.apache.commons.math3.util.MathArraysTest::testLinearCombinationWithSingleElementArray'

# Using . separator (also works)
python3 main_apache_math3.py \
  'data/raw/callgraph.json' \
  'data/raw/test2' \
  'org.apache.commons.math3.util.MathArraysTest.testLinearCombinationWithSingleElementArray'

# Another example with Complex class
python3 main_apache_math3.py \
  'data/raw/callgraph.json' \
  'data/raw/test' \
  'org.apache.commons.math3.complex.ComplexTest.testReciprocalZero'
```

## Output

The script automatically determines the output directory based on the callgraph filename:
- `callgraph.json` → `data/outputs/reconstructions/`
- `callgraph2.json` → `data/outputs/reconstructions2/`
- `callgraph3.json` → `data/outputs/reconstructions3/`

Reports are saved as: `langgraph_analysis_YYYYMMDD_HHMMSS.txt`

## Error Messages

### Missing arguments
```
Usage: python3 main_apache_math3.py <callgraph_json> <tests_root> <test_name>

Example:
  python3 main_apache_math3.py 'data/raw/callgraph.json' 'data/raw/test2' 'org.apache.commons.math3.util.MathArraysTest::testLinearCombinationWithSingleElementArray'

Arguments:
  callgraph_json: Path to the callgraph JSON file
  tests_root    : Path to the test directory
  test_name     : Fully qualified test name (use :: or . as separator)
```

### File not found
If the callgraph or test directory doesn't exist, you'll see:
```
✗ Error loading callgraph: [Errno 2] No such file or directory: 'data/raw/callgraph.json'
✗ Test directory not found: data/raw/test
```

## Configuration

The script configuration when started:
```
Configuration:
  Callgraph: data/raw/callgraph.json
  Tests root: data/raw/test2
  Test name: org.apache.commons.math3.util.MathArraysTest.testLinearCombinationWithSingleElementArray
  Output dir: data/outputs/reconstructions2
============================================================
```

## Test Name Format

The test name is injected into the LLM prompt, so the agent knows which specific test to analyze:

```
OBJECTIVE: Determine the execution path for test: 'org.apache.commons.math3.util.MathArraysTest.testLinearCombinationWithSingleElementArray'.
```

Both formats are supported and automatically normalized:
- `ClassName::methodName` → converted to `ClassName.methodName`
- `ClassName.methodName` → used as-is

## Advanced: Multiple Test Runs

To analyze multiple tests, you can create a simple shell script:

```bash
#!/bin/bash
# analyze_tests.sh

CALLGRAPH="data/raw/callgraph.json"
TESTROOT="data/raw/test2"

python3 main_apache_math3.py "$CALLGRAPH" "$TESTROOT" \
  "org.apache.commons.math3.util.MathArraysTest::testLinearCombinationWithSingleElementArray"

python3 main_apache_math3.py "$CALLGRAPH" "$TESTROOT" \
  "org.apache.commons.math3.util.MathArraysTest::testLinearCombinationInfinite"

python3 main_apache_math3.py "$CALLGRAPH" "$TESTROOT" \
  "org.apache.commons.math3.complex.ComplexTest::testReciprocalZero"
```

Then run:
```bash
chmod +x analyze_tests.sh
./analyze_tests.sh
```

## Requirements

Before running, ensure:
1. ✅ MLX server is running on `http://localhost:8080`
2. ✅ Callgraph JSON file exists
3. ✅ Test directory exists with Java test files
4. ✅ Python dependencies installed: `langgraph`, `requests`

## Previous Behavior (Old Version)

In the old version, the paths were hardcoded:
```python
# OLD - Don't use this anymore
callgraph_json = "data/raw/callgraph3.json"
tests_root = "data/raw/test3"
# Test name was hardcoded in the prompt
```

Now everything is configurable via command-line arguments! 🎯
