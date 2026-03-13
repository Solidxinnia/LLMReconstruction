"""Test suite discovery and access utilities."""

from pathlib import Path
from typing import List, Dict, Optional
import re


def find_test_samples(test_dir: str, max_samples: Optional[int] = None) -> List[Dict[str, str]]:
    samples: List[Dict[str, str]] = []
    root = Path(test_dir)
    if not root.exists():
        return samples
    try:
        java_files = list(root.rglob("*.java"))
        scan_list = java_files if max_samples is None else java_files[: max_samples * 2]
        for p in scan_list:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "@Test" in content or "test" in p.name.lower():
                m = re.search(r"class\s+(\w+)", content)
                class_name = m.group(1) if m else p.stem
                lines = content.split("\n")[:30]
                sample = "\n".join(lines)
                samples.append({
                    "file": str(p.relative_to(root)),
                    "class": class_name,
                    "sample": sample,
                })
                if max_samples is not None and len(samples) >= max_samples:
                    break
    except Exception:
        return samples
    return samples


def get_tests_for_class(tests: List[Dict[str, str]], class_name: str) -> str:
    filtered = [t for t in tests if class_name.lower() in t.get("class", "").lower()]
    if not filtered:
        return f"No test samples found for class '{class_name}'"
    out: List[str] = []
    for test in filtered[:2]:
        out.append(f"Test file: {test['file']}")
        out.append(f"Test class: {test['class']}")
        out.append("Sample code:")
        out.append(f"```java\n{test['sample']}\n```")
    return "\n".join(out)


def get_test_content(filename: str, tests_root: str = "data/raw/test") -> str:
    root = Path(tests_root)
    target = root / filename
    if not target.exists():
        for p in root.rglob("*.java"):
            if filename in str(p):
                target = p
                break
    if target.exists():
        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
            return f"Test file: {target.name}\n```java\n{content[:2000]}\n```"
        except Exception as e:
            return f"Error reading test file: {e}"
    return f"Test file '{filename}' not found"
