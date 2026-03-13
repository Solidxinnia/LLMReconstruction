export OPENAI_API_BASE="http://localhost:8000/v1"
export OPENAI_API_KEY="none"
export MSWEA_COST_TRACKING="ignore_errors"
mini -y --model openai/google/gemma-3-12b-it   -c mini_textbased.yaml   -c model.model_class=litellm_textbased   -c agent.step_limit=150   --task 'OBJECTIVE
Perform Static Analysis and Mental Tracing to determine the full execution path of the test- org.apache.commons.math3.complex.ComplexTest::testReciprocalZero across multiple project IDs. Act as the JVM interpreter. Do NOT compile or execute code.

RESOURCES & TOOLS:
1. Test Definition: /mnt/data/LLMReconstruction/data/raw/test/java/org/apache/commons/math3/complex
2. Target Project IDs: /mnt/data/LLMReconstruction/project_ids.txt
3. Source Fetcher: Execute python3 /mnt/data/LLMReconstruction/data/get_mutated_code.py "<fully_qualified_method_name (args)>" <ID>. (e.g. python3 /mnt/data/LLMReconstruction/data/get_mutated_code.py "org.apache.commons.math3.analysis.function.Sin:value(double)" Math-2_33_1_56_65)
4. Output Path: /mnt/data/LLMReconstruction/data/outputs/reconstruction_results.json

TECHNICAL CONSTRAINTS:
1. Search the test method only inside the Test Definition directory.
2. The Source Fetcher must ONLY be used for production methods. The test method must be read directly from the Test Definition directory.
3. Perform Mental Tracing only. Do not use mvn, javac, or runtime execution.
4. Do not include test lines in output. ONLY include production lines.

EXECUTION WORKFLOW:

1. Initialization
   - Locate and read the body of the test.
   - Load the list of Project IDs.

2. For each Project ID

   a. Find the execution path of the test tracing the argument values passed from the test.
   b. Analyze all the methods called by the test using Source Fetcher. Please give arguments found from the test while using Source Fetcher.
   c. Example reasoning: "The test org.apache.commons.math3.complex.ComplexTest.testScalarDivideNaN creates x = new Complex(3.0, 4.0) (so isNaN = false) and a divisor equal to Double.NaN. It then compares x.divide(new Complex(Double.NaN)) and x.divide(Double.NaN). As the test calls divide(Complex divisor) method, I need to check its content using Source Fetcher. Then I will analyze what happens in divide(Complex divisor)."
   Example outcome of the reasoning:
   {
   "id": "Math-57_3_1_65",
    "method_coverage": {
        "org.apache.commons.math3.analysis.FunctionUtils:toUnivariateDifferential": [
            "45|1", → line 45, hit once
            "46|3", → line 46, hit thrice
            "51|1|50% (1/2)", → line 51, hit once, 1 of 2 branches covered (50%)
            "54|1" → line 54, hit once
        ],
        "org.apache.commons.math3.analysis.function.Sin:value(double)": [
            "7|1"
        ]
    } 
   }
   d. Perform LINE-BY-LINE execution analysis based on argument values and record method coverage:
   Produce a JSON object per Project ID:
    {
        "id": "Project_id",
        "method_coverage": {
            "fully.qualified.ClassName:methodName(params)": [
                "lineNumber|hitCount", → "lineNumber" is the relative line number of the production method, "hitCount" is the number of times that line was executed 
                "lineNumber|hitCount|condition% (covered/total)" → "condition%" is the percentage of the conditions covered in that line, "covered" is how many conditions were covered and "total" is the total number of conditions in that line
            ]
        }
    }
   e. Follow these instructions for condition coverage:
        1. if (condition) → 2 branches (true, false)
        2. if (a && b) → 4 branches (both true; a true b false; a false b true; both false)
        3. if (a || b) → 4 branches (both true; a true b false; a false b true; both false)
        4. condition ? x : y → 2 branches (true → x, false → y)
   f. Stop only when all reachable methods in the execution path have been analyzed with line-level coverage.

4. Finalization
Append each completed JSON object to the output file.

ACCEPTANCE CRITERIA
- Every Project ID must produce one JSON entry.
- Line hit counts must reflect the simulated execution path.
- Branch coverage must use correct branch counts.
- JSON output must be syntactically valid.'  2>&1 | tee experiment_log.txt