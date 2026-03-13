import subprocess
import os
import json

# --- Configuration ---
PROJECTS_FILE = "/mnt/data/LLMReconstruction/mutation_ids.txt"
LOG_FILE = "mini_swe_experiment_log.txt"
TEMP_OUTPUT = "/mnt/data/LLMReconstruction/data/outputs/reconstruction_results.json"
MASTER_OUTPUT = "/mnt/data/LLMReconstruction/data/outputs/master_reconstruction_results.json"

# Environment Setup
env_vars = os.environ.copy()
env_vars["OPENAI_API_BASE"] = "http://localhost:8000/v1"
env_vars["OPENAI_API_KEY"] = "none"
env_vars["MSWEA_COST_TRACKING"] = "ignore_errors"

def append_json_result(project_id):
    """Reads the single result, appends to master list, then cleans up."""
    if not os.path.exists(TEMP_OUTPUT):
        print(f"Warning: No output file found at {TEMP_OUTPUT} for {project_id}")
        return

    try:
        with open(TEMP_OUTPUT, "r") as f:
            new_entry = json.load(f)

        master_data = []
        if os.path.exists(MASTER_OUTPUT):
            with open(MASTER_OUTPUT, "r") as f:
                try:
                    master_data = json.load(f)
                    if not isinstance(master_data, list):
                        master_data = [master_data]
                except json.JSONDecodeError:
                    master_data = []

        master_data.append(new_entry)

        with open(MASTER_OUTPUT, "w") as f:
            json.dump(master_data, f, indent=4)
        
        print(f"Successfully appended {project_id}. Cleaning up temp file...")
        os.remove(TEMP_OUTPUT) # Ensure the next run doesn't read old data
        
    except Exception as e:
        print(f"Error processing results for {project_id}: {e}")

def run_mini_agent(project_id):
    print(f"\n>>> [STARTING] Project: {project_id}")
    
    task_description = f"""OBJECTIVE
Perform Static Analysis and Mental Tracing to determine the full execution path of the test- org.apache.commons.math3.ode.nonstiff.DormandPrince853IntegratorTest::testEventsScheduling for a project.

RESOURCES & TOOLS:
1. Target Project ID: {project_id}
2. Source Fetcher: Execute python3 /mnt/data/LLMReconstruction/data/get_mutated_code.py "<fully_qualified_method_name (args)>" {project_id}
3. Output Path: /mnt/data/LLMReconstruction/data/outputs/reconstruction_results.json

TECHNICAL CONSTRAINTS:
1. Perform Mental Tracing only. Do not use mvn, javac, or runtime execution.
2. Do not include test lines in output. ONLY include source code lines.

Initialization
   - Locate and read the body of the test.
   - Trace all methods invoked by the test
   - Write json output in /mnt/data/LLMReconstruction/data/outputs/reconstruction_results.json following this-
        EXAMPLE WITH ARGUMENT TRACING:
        Test: Complex.ZERO.reciprocal() where Complex.ZERO has real=0.0, imaginary=0.0

        Method body:
        1: public Complex reciprocal() {{
        2:     if (isNaN) {{                                // 2 branches: true/false
        3:         return NaN;
        4:     }}
        5:     if (real == 0.0 && imaginary == 0.0) {{     // 4 branches: TT/TF/FT/FF
        6:         return INF;  // This line executes
        7:     }}
        8:     if (isInfinite) {{                           // This line does NOT execute (already returned)
        9:         return ZERO;
        10:     }}
        11:     }}

        Reasoning: "Test calls Complex.ZERO.reciprocal(). Complex.ZERO has real=0.0 and imaginary=0.0. 
        In reciprocal(), line 2 checks isNaN (false for ZERO), so only the false branch executes (1/2 branches).
        Line 5 checks if (real == 0.0 && imaginary == 0.0) which is TRUE (both conditions true, so 1/4 branches covered).
        Line 6 executes and returns INF. Lines 8+ do not execute because we already returned."

        Output: 
        [
            "1|1|50% (1/2)",      // Line 1: method signature with implicit return branch (normal/exception)
            "2|1|50% (1/2)",      // Line 2: if (isNaN) - only false branch executes
            "5|1|25% (1/4)",      // Line 5: if (real == 0.0 && imaginary == 0.0) - only TT branch executes
            "6|1"                 // Line 6: return statement (no branches)
        ]  

        RESPONSE FORMAT (JSON):
        {{
            "id": "Math-57_3_1_65",
            "method_coverage": {{
                "fully.qualified.ClassName:methodName(params)": [
                "lineNumber|hitCount", → "lineNumber" is the relative line number of the production method, "hitCount" is the number of times that line was executed 
                "lineNumber|hitCount|condition% (covered/total)" → "condition%" is the percentage of the conditions covered in that line, "covered" is how many conditions were covered and "total" is the total number of conditions in that line
                ]
            }}
        }}

        EXAMPLE OUTPUT:
       {{
            "id": "Math-5_73_61_65",
            "method_coverage": {{
                "org.apache.commons.math3.analysis.FunctionUtils:toUnivariateDifferential": [
                    "5|1|50% (1/2)" → line 5, hit once, 1 of 2 branches covered (50%)
                    "10|2|25% (1/4)" → line 10, hit twice, 1 of 4 branches covered (25%)
                    "15|11|100% (2/2)" → line 15, hit eleven times, both branches covered (100%)
                ],
                "org.apache.commons.math3.analysis.function.Sin:value(double)": [
                    "5|2"
                ]
            }}
        }}
"""

    # --- ADDED --exit_on_finish TO AUTOMATE EXIT ---
    cmd = [
        "mini", "-y",
        "--exit-immediately", 
        "--model", "openai/google/gemma-3-12b-it",
        "-c", "mini_textbased.yaml",
        "-c", "model.model_class=litellm_textbased",
        "-c", "agent.step_limit=150",
        "--task", task_description
    ]

    with open(LOG_FILE, "a") as log:
        log.write(f"\n--- RUN: {project_id} ---\n")
        process = subprocess.Popen(cmd, env=env_vars, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        process.wait()
    
    append_json_result(project_id)

def main():
    if not os.path.exists(PROJECTS_FILE):
        print(f"Error: {PROJECTS_FILE} not found.")
        return

    with open(PROJECTS_FILE, "r") as f:
        project_ids = [line.strip() for line in f if line.strip()]

    for p_id in project_ids:
        run_mini_agent(p_id)
        print(f">>> [COMPLETED] Project: {p_id}\n" + "="*40)

if __name__ == "__main__":
    main()