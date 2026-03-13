export OPENAI_API_BASE="http://localhost:8000/v1"
export OPENAI_API_KEY="none"
export MSWEA_COST_TRACKING="ignore_errors"

mini -y --model openai/google/gemma-3-12b-it   -c mini_textbased.yaml   -c model.model_class=litellm_textbased   -c agent.step_limit=150   --task 'OBJECTIVE
Perform Static Analysis and Mental Tracing to determine the full execution path of org.apache.commons.math3.complex.ComplexTest::testReciprocalZero across multiple project IDs. Act as the JVM interpreter. Do NOT compile or execute code.

RESOURCES & TOOLS
1. Test Definition: /mnt/data/LLMReconstruction/data/raw/test
2. Target Project IDs: /mnt/data/LLMReconstruction/project_ids.txt
3. Source Fetcher:
   python3 /mnt/data/LLMReconstruction/data/get_mutated_code.py "<FQCN:methodName>" <ID>
4. Output Path:
   /mnt/data/LLMReconstruction/data/outputs/reconstruction_results.json

TECHNICAL CONSTRAINTS
1. Search the test method only inside the Test Definition directory.
2. The Source Fetcher must ONLY be used for production methods. The test method must be read directly from the Test Definition directory. Do NOT attempt to fetch the test method using the Source Fetcher.
3. Perform Mental Tracing only. Do not use mvn, javac, or runtime execution.
4. Evaluate logical operators with strict branch enumeration:
   - if(condition) → 2 branches
   - && and || → 4 branches (TT, TF, FT, FF)
   - ternary ?: → 2 branches.

EXECUTION WORKFLOW

1. Initialization
   - Locate and read the body of ComplexTest::testReciprocalZero.
   - Load the list of Project IDs.

2. For each Project ID

   a. Identify all production methods directly called by the test.

   b. For each discovered method:
      - Fetch its source using the Source Fetcher.
      - Trace argument values passed from the test.
      - Evaluate conditional statements using those concrete values.

   c. Perform line-by-line execution simulation:
      - Determine which lines execute.
      - Calculate hitCount per line.

   d. Branch Coverage
      - For every conditional line (if, switch, ternary, &&, ||)
      - Compute coverage percentage as (covered/total).

   e. Continue recursive discovery:
      - If the method calls another production method,
        fetch and analyze that method as well.

   f. Special tracing rules:
      - Assert.assertEquals(a,b) implies a.equals(b) call.
      - Assert.assertTrue(condition) evaluates the condition only.
      - Assert.assertSame(a,b) performs == comparison.

   g. Handle additional patterns:
      - Method overloads
      - Wrapper or factory methods
      - Anonymous classes
      - Returned objects whose methods are invoked.

   h. Stop only when all reachable methods in the execution path
      have been analyzed with line-level coverage.

3. Recording Results
   Produce a JSON object per Project ID:

{
"id": "Project_id",
"method_coverage": {
"fully.qualified.ClassName:methodName(params)": [
"lineNumber|hitCount",
"lineNumber|hitCount|condition% (covered/total)"
]
}
}

4. Finalization
Append each completed JSON object to the output file.

ACCEPTANCE CRITERIA
- Every Project ID must produce one JSON entry.
- Line hit counts must reflect the simulated execution path.
- Branch coverage must use correct branch counts.
- JSON output must be syntactically valid.'  2>&1 | tee experiment_log.txt