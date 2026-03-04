# LLM Reconstruction

This project reconstructs codebases using LLMs, given callgraph, test suite, and code coverage information from Defects4J projects.

## Structure
- `config/`: Configuration files
- `data/`: Input and output data
- `src/`: Source code
- `prompts/`: Prompt templates

## Usage

1. Prepare input data in `data/raw/`:
	- `cov.json`: coverage JSON
	- `callgraph.csv`: method callgraph CSV
	- `test/`: root folder containing Java test suites

2. Start the local MLX LLM server (example):
	- `python -m mlx_lm.server --model mlx-community/Qwen2.5-Coder-14B-Instruct-4bit --max-tokens 4096 --port 8080`

3. Run `main.py` to start the pipeline:
	- Interactive: `python main.py`
	- Demo: `python main.py demo`
	- Custom task: `python main.py "Analyze Complex class structure"`

Outputs will be saved under `data/outputs/reconstructions/`.
