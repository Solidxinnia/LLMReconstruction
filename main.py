#!/usr/bin/env python3
"""
Main entry point for the MLX code question pipeline.

This script runs the orchestrator that queries a local MLX LLM server
to analyze coverage, callgraph relationships, test suites, and method bodies.
"""

import json
import hashlib
import re
import time
from typing import TypedDict, List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from src.llm_interface import MLXClient, MLXConfig
from src.data_loader import DataLoader
from src.analysis_tools import AnalysisTools
from src.result_saver import save_analysis as save_analysis_file, save_detailed_log as save_log_file


class AgentState(TypedDict):
	task: str
	coverage_context: str
	callgraph_context: str
	test_context: str
	tools_output: List[str]
	iteration: int
	version: str
	tool_requests: List[Dict[str, Any]]
	responses: List[Dict[str, Any]]
	lines_to_execute: List[str]
	done: bool
	current_understanding: str


class MLXOrchestrator:
	def __init__(self, config: Optional[MLXConfig] = None):
		self.config = config or MLXConfig()
		self.data_loaded = False
		self.project_data: Dict[str, Any] = {}
		self.tools_registry: Dict[str, Any] = {}
		self.output_dir = Path("data/outputs/reconstructions")
		self.output_dir.mkdir(parents=True, exist_ok=True)
        
		print("Initializing MLX Orchestrator...")
		print(f"MLX Server: {self.config.base_url}")
		print(f"Model: {self.config.model}")
        
		# Initialize client and test connection
		self.client = MLXClient(self.config)
		if not self._test_connection():
			print("\n Could not connect to MLX server.")
			print("Please make sure it's running with:")
			print(f"python -m mlx_lm.server --model {self.config.model} --max-tokens {self.config.max_tokens} --port 8080")
			raise ConnectionError("MLX server not reachable")
    
	def _test_connection(self) -> bool:
		"""Test MLX server connection via client"""
		ok = self.client.test_connection()
		if ok:
			print("✓ MLX server is running!")
		else:
			print("✗ Connection error: cannot reach MLX server")
		return ok

	def call_mlx(self, iteration: int, prompt: str, system_prompt: str = None) -> str:
		"""Call MLX via client"""
		print(f"Calling llm with {len(prompt)} chars prompt...")
		print(prompt)
		start_time = time.time()
		content = self.client.call(prompt, system_prompt)

		elapsed = time.time() - start_time
		if not content.startswith("Error:"):
			print(f"✓ llm response received in {elapsed:.1f}s ({len(content)} chars)")
		else:
			print(content)
		return content
    
	def _load_data(self):
		"""Load project data"""
		if self.data_loaded:
			return
        
		print("\nLoading project data...")
		try:
			loader = DataLoader()
			self.project_data = loader.load(
				coverage_path="data/raw/cov.json",
				callgraph_csv="data/raw/callgraph_string_utils.csv",
				tests_root="data/raw/test/string_utils",
			)
			# Initialize tools on loaded data
			self.tools = AnalysisTools(self.project_data, self.output_dir, tests_root=loader.tests_root)
			self._register_tools()
			self.data_loaded = True
            
			print("✓ Project data loaded:")
			print(f"  - Coverage: {len(self.project_data.get('coverage', {}).get('buggy', {}).get('method_coverage', {}))} methods")
			print(f"  - Callgraph: {self.project_data.get('callgraph', {}).get('total_relationships', 0)} relationships")
			print(f"  - Tests: {len(self.project_data.get('tests', []))} samples")
            
		except Exception as e:
			print(f"✗ Error loading data: {e}")
			raise
    
	def _register_tools(self):
		"""Register available tools"""
        
		self.tools_registry = {
			"get_coverage_info": self.tools.get_coverage_info,
			"get_coverage_lines": self.tools.get_coverage_lines,
			"get_callgraph": self.tools.get_callgraph,
			"get_method_body": self.tools.get_method_body,
			"get_tests_for_class": self.tools.get_tests_for_class,
			"get_all_tests": self.tools.get_all_tests,
			"get_test_content": self.tools.get_test_content,
			"save_analysis": self.save_analysis,
		}
    
	def save_analysis(self, analysis: str, filename: str = None) -> str:
		"""Delegate to result_saver.save_analysis"""
		return save_analysis_file(self.output_dir, analysis, filename)
    
	def run_question(self, task: str = None, version: str = "buggy", max_iterations: int = 5) -> Dict[str, Any]:
		"""Run question with MLX"""
        
		# Load data
		self._load_data()
        
		# Initial state
		state: AgentState = {
			"task": task,
			"coverage_context": "Coverage input disabled.",
			"callgraph_context": self.tools.get_callgraph(),
			"test_context": self.tools.get_all_tests(limit=100, include_samples=False, force_refresh=True),
			"tools_output": [],
			"iteration": 0,
			"version": version,
			"tool_requests": [],
			"responses": [],
			"lines_to_execute": [],
			"done": False,
			"current_understanding": "Starting analysis...",
		}
        
		print(f"\n{'='*60}")
		print(f"MLX question: {task}")
		print(f"Version: {version}")
		print(f"Max iterations: {max_iterations}")
		print(f"{'='*60}")
        
		for iteration in range(max_iterations):
			print(f"\n[ITERATION {iteration + 1}/{max_iterations}]")
            
			# Build prompt for MLX
			prompt = self._build_question_prompt(state)
			system_prompt = self._get_system_prompt()
			#print(f"Prompt: {prompt}")
            
			# Call MLX
			print("Calling MLX for analysis...")
			response = self.call_mlx(iteration, prompt, system_prompt)
            
			if response.startswith("Error:"):
				print(f"MLX error: {response}")
				state["tools_output"].append(f"Iteration {iteration}: {response}")
				break
            
			# Parse response
			print("Parsing llm response...")
			requests, done, reasoning, lines_to_execute = self._parse_mlx_response(response)
            
			state["current_understanding"] = reasoning or "No reasoning provided"
			if lines_to_execute:
				state["lines_to_execute"] = lines_to_execute
            
			if done:
				print("MLX marked task as complete")
				state["done"] = True
				break
            
			if not requests:
				print("MLX didn't request any information")
				state["tools_output"].append(f"Iteration {iteration}: No requests made")
				# Ask MLX to continue or finish
				continue_prompt = f"Previous response: {response[:200]}...\n\nYou haven't requested a tool. Do you need to see a specific method body or test sample to continue the branch analysis?"
				continue_response = self.call_mlx(iteration, continue_prompt, system_prompt)
				# Update current understanding with follow-up reasoning even if no tool is requested
				_, continue_done, continue_reasoning, continue_lines = self._parse_mlx_response(continue_response)
				if continue_reasoning:
					state["current_understanding"] = continue_reasoning
				if continue_lines:
					state["lines_to_execute"] = continue_lines
				
				if continue_done or "done" in continue_response.lower():
					state["done"] = True
					break
				else:
					continue
            
			# Execute tool requests
			print(f"Executing {len(requests)} tool requests...")
			for i, req in enumerate(requests):
				print(f"  Request {i+1}: {req.get('type')}")
				result = self._execute_tool_request(req, state)
                
				# Store result
				state["tools_output"].append(f"{req.get('type')}: {result[:100]}...")
				state["responses"].append({
					"iteration": iteration,
					"request": req,
					"result": result[:500]  # Store truncated result
				})
                
				# Update context based on tool type
				if req.get("type") == "get_callgraph":
					state["callgraph_context"] = result[:1000]
				elif req.get("type") in ["get_tests_for_class", "get_all_tests", "get_test_content"]:
					state["test_context"] = result[:1000]
            
			state["iteration"] += 1
        
		# Save final analysis
		print(f"\n{'='*60}")
		print("question COMPLETE")
		print(f"{'='*60}")
		print(f"Iterations completed: {state['iteration']}")
		print(f"Tool requests made: {len(state['responses'])}")
		print(f"Task complete: {state['done']}")
        
		# Generate final analysis
		final_analysis = self._generate_final_analysis(state)
		save_result = self.save_analysis(final_analysis, f"final_analysis_{version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        
		print(f"\n{save_result}")
        
		# Save detailed log
		self._save_detailed_log(state, version)
        
		return state
    
	def _build_question_prompt(self, state: AgentState) -> str:
		"""Build prompt for MLX question"""
        
		# Build a clear summary of what tools have been called
		tools_called = {}
		if state['responses']:
			for resp in state['responses']:
				req = resp.get('request', {})
				tool_type = req.get('type', 'unknown')
				args = req.get('args', {})
				result = resp.get('result', '')
				
				# Group by tool type
				if tool_type not in tools_called:
					tools_called[tool_type] = []
				tools_called[tool_type].append({
					'args': args,
					'result': result[:500]  # Show more of the result
				})
		
		# Format tool history clearly
		tool_history = "INFORMATION YOU ALREADY HAVE:\n"
		if tools_called:
			for tool_type, calls in tools_called.items():
				tool_history += f"\n✓ {tool_type} (called {len(calls)} time(s)):\n"
				for call in calls[-2:]:  # Show last 2 calls of each type
					tool_history += f"  Args: {call['args']}\n"
					tool_history += f"  Result: {call['result'][:300]}...\n"
		else:
			tool_history += "None yet - this is your first request.\n"
			
		available_tests = [t.get('file') for t in self.project_data.get('tests', [])]
		test_menu = ", ".join(available_tests[:50]) # List names, not content
	
		prompt = f"""TASK: {state['task']}
VERSION: {state['version']}
ITERATION: {state['iteration'] + 1}

YOUR CURRENT UNDERSTANDING:
{state['current_understanding']}

{tool_history}

AVAILABLE INFORMATION (not yet requested):
1. CALLGRAPH RELATIONSHIPS:
{state['callgraph_context'][:600]}

2. TEST FILES AVAILABLE:
{test_menu}

YOUR PROPOSED LINES/METHODS TO EXECUTE SO FAR:
{", ".join(state['lines_to_execute']) if state['lines_to_execute'] else "None yet"}

INSTRUCTIONS:
- DO NOT request tools you've already called (see "INFORMATION YOU ALREADY HAVE" above)
- If you have enough information to determine execution paths, set "done": true
- If you need MORE information, request NEW tools with different arguments
- Focus on identifying which production methods are called by the tests

What do you need next?"""
        
		return prompt
    
	def _get_system_prompt(self) -> str:
		"""Get system prompt for MLX"""
		return """YOUR ROLE: You are an intelligent java code analyst, helping the user find execution path of the code for test suite- parsesSimpleObject(). analysing the test suites given, decide which lines should be executed. based on your decision, ask the user what tools you need next.

AVAILABLE TOOLS:
- get_callgraph(method_filter=None) - Get production code method relationships from the project
- get_method_body(method_name) - Get production code method implementation (from callgraph)
- get_all_tests(limit=None, include_samples=False) - List all discovered tests (optionally include samples)
- get_test_content(filename) - Get full test file content including all test methods
- save_analysis(analysis, filename) - Save your analysis

IMPORTANT DISTINCTIONS:
- Production code methods are in the CALLGRAPH - use get_method_body() to see their implementation
- Test methods are in TEST FILES - use get_test_content() to see test method implementations
- To understand what a test does, read the test file with get_test_content()
- To understand what production code does, use get_method_body()

INSTRUCTIONS:
1. infer which lines/methods should be executed from tests + callgraph.
2. Put those in `lines_to_execute` as method signatures or file:line if known.
3. Decide what additional information you need (do NOT repeat identical tool requests).
4. Request specific tools with clear arguments.
5. Provide your reasoning and mark as done when you have enough information.

RESPONSE FORMAT (JSON):
{{
  "reasoning": "Your analysis of current information and what you need next",
	"lines_to_execute": ["Class.method(...)", "file.java:123"],
  "requests": [
	{{"type": "tool_name", "args": {{"arg1": "value1", "arg2": "value2"}}}}
  ],
  "done": false/true
}}

Example:
{{
	"reasoning": "I see test file StringUtilsTest.java. I need to read the test methods to understand what they test. Then I'll use get_method_body to see the production code implementations.",
	"lines_to_execute": ["StringUtils.reverse(String)", "StringUtils.isPalindrome(String)"],
  "requests": [
	{{"type": "get_test_content", "args": {{"filename": "StringUtilsTest.java"}}}},
	{{"type": "get_method_body", "args": {{"method_name": "reverse"}}}}
  ],
  "done": false
}}
"""

	def _parse_mlx_response(self, response: str) -> tuple:
		# Handle Markdown blocks
		if "```json" in response:
			response = response.split("```json")[-1].split("```")[0]
		
		json_match = re.search(r'\{.*\}', response, re.DOTALL)
		if json_match:
			try:
				data = json.loads(json_match.group(0))
				reasoning = data.get("reasoning", "")
				if not reasoning:
					reasoning = response.strip()
				return data.get("requests", []), data.get("done", False), reasoning, data.get("lines_to_execute", [])
			except json.JSONDecodeError:
				pass
		
		# If it fails, do NOT mark as done. Use raw response as reasoning so it changes.
		return [], False, response.strip(), []

	def _request_key(self, request: Dict[str, Any]) -> str:
		tool_type = request.get("type", "")
		args = request.get("args", {})
		if not isinstance(args, dict):
			args = {}
		return f"{tool_type}|{json.dumps(args, sort_keys=True, ensure_ascii=False)}"

	def _execute_tool_request(self, request: Dict[str, Any], state: AgentState) -> str:
		"""Execute a tool request, avoiding duplicates."""
		tool_type = request.get("type")
		args = request.get("args", {})
		request_key = self._request_key(request)

		# Avoid repeating identical tool requests; reuse previous result.
		for resp in reversed(state.get("responses", [])):
			if self._request_key(resp.get("request", {})) == request_key:
				return (
					"[DUPLICATE REQUEST] This exact tool with these arguments was already called. Previous result:\n"
					+ (resp.get("result", "") or "")
				)

		if tool_type in self.tools_registry:
			try:
				return self.tools_registry[tool_type](**args)
			except TypeError as e:
				return f"Argument error for {tool_type}: {e}"
			except Exception as e:
				return f"Error executing {tool_type}: {str(e)}"
		else:
			available = ", ".join(self.tools_registry.keys())
			return f"Unknown tool: {tool_type}. Available: {available}"
    
	def _generate_final_analysis(self, state: AgentState) -> str:
		"""Generate final analysis based on question results"""
        
		analysis = f"""CODE ANALYSIS REPORT
Generated: {datetime.now().isoformat()}
Task: {state['task']}
Version: {state['version']}
Iterations: {state['iteration']}
Tool Requests: {len(state['responses'])}

{'='*60}
FINAL UNDERSTANDING
{'='*60}

{state['current_understanding']}

PROPOSED LINES/METHODS TO EXECUTE
{'='*60}

{', '.join(state.get('lines_to_execute', [])) if state.get('lines_to_execute') else 'None provided'}

{'='*60}
KEY FINDINGS
{'='*60}

1. COVERAGE ANALYSIS:
{state['coverage_context']}

2. CALLGRAPH ANALYSIS:
{state['callgraph_context']}

3. TEST ANALYSIS:
{state['test_context']}

{'='*60}
TOOL EXECUTION HISTORY
{'='*60}

"""
        
		for i, resp in enumerate(state['responses']):
			req = resp.get('request', {})
			result = resp.get('result', '')
            
			analysis += f"\n{i+1}. {req.get('type', 'unknown')}:\n"
			analysis += f"   Args: {req.get('args', {})}\n"
			analysis += f"   Result: {result[:300]}...\n"
        
		analysis += f"\n{'='*60}\nRECOMMENDED RECONSTRUCTION APPROACH\n{'='*60}\n"
        
		'''# Add reconstruction suggestions based on findings
		if "add" in state['current_understanding'].lower():
			analysis += "1. Start with Complex.add() method implementation\n"
		if "coverage" in state['current_understanding'].lower():
			analysis += "2. Focus on methods with high test coverage first\n"
		if "test" in state['current_understanding'].lower():
			analysis += "3. Ensure implementation matches test expectations\n"
        
		analysis += "4. Implement basic arithmetic operations (add, subtract, multiply, divide)\n"
		analysis += "5. Add mathematical functions (abs, sqrt, log, exp)\n"
		analysis += "6. Handle edge cases (NaN, Infinity, zero)\n"
		analysis += "7. Add utility methods (equals, hashCode, toString)\n"
		'''
        
		return analysis
    
	def _save_detailed_log(self, state: AgentState, version: str):
		"""Delegate to result_saver.save_detailed_log"""
		print(save_log_file(self.output_dir, state, version))
    
	def run_demo(self):
		"""Run a demo question"""
		print("\n" + "="*60)
		print("MLX question DEMO")
		print("="*60)
        
		task = "Analyze the structure of Complex class from Apache Commons Math to understand how to reconstruct it"
        
		result = self.run_question(
			task=task,
			version="buggy",
			max_iterations=3  # Quick demo
		)
        
		print("\n" + "="*60)
		print("DEMO SUMMARY")
		print("="*60)
		print(f"Task: {task}")
		print(f"Iterations: {result['iteration']}")
		print(f"Tool requests: {len(result['responses'])}")
		print(f"Complete: {'Yes' if result['done'] else 'No'}")
        
		if result['current_understanding']:
			print(f"\nFinal understanding:\n{result['current_understanding'][:500]}...")
        
		print("="*60)


def main():
	"""Main entry point"""
    
	print("llm Code question System")
	print("="*60)
    
	# Configure MLX
	config = MLXConfig(
		base_url="http://localhost:8080/v1",
		model="mlx-community/Qwen2.5-Coder-14B-Instruct-4bit",
		max_tokens=65536,  # Reduced for faster responses
		temperature=0.1,
		timeout=720.0
	)
    
	# Initialize orchestrator
	try:
		orchestrator = MLXOrchestrator(config)
        
		# Run demo or full question
		import sys
		if len(sys.argv) > 1:
			if sys.argv[1] == "demo":
				orchestrator.run_demo()
			else:
				# Custom task
				task = " ".join(sys.argv[1:])
				orchestrator.run_question(task=task, max_iterations=20)
		else:
			# Interactive mode
			print("\nOptions:")
			print("1. Run demo (3 iterations)")
			print("2. Run full question (20 iterations)")
			print("3. Custom task")
            
			choice = input("\nSelect option (1-3): ").strip()
            
			if choice == "1":
				orchestrator.run_demo()
			elif choice == "2":
				task = "You are an intelligent code analyst. you have acces to test suites, callgraph relationships and method bodies. find the execution path of the project for test suite - parsesSimpleObject()."
				orchestrator.run_question(task=task, max_iterations=20)
			else:
				task = input("Enter your analysis task: ").strip()
				if not task:
					task = "Analyze the Complex class structure"

				iterations = input("Max iterations [20]: ").strip()
				iterations = int(iterations) if iterations.isdigit() else 20
                
				orchestrator.run_question(task=task, max_iterations=iterations)
                
	except ConnectionError as e:
		print(f"\nError: {e}")
		print("\nPlease start MLX server with:")
		print("python -m mlx_lm.server --model mlx-community/Qwen2.5-Coder-14B-Instruct-4bit --max-tokens 65536 --port 8080")
	except Exception as e:
		print(f"\nUnexpected error: {e}")
		import traceback
		traceback.print_exc()


if __name__ == "__main__":
	main()
