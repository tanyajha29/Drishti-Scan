import json
import re
from pathlib import Path
from typing import Any, Dict, List


class RuleEngineScanner:
    """
    Generic rule-driven scanner that loads regex-based vulnerability rules
    from a centralized JSON library.
    """

    def __init__(self) -> None:
        self.rules = self._load_rules(self._resolve_rules_path())

    def _resolve_rules_path(self) -> Path:
        """
        Prefer the centralized backend/rules directory but gracefully fall back
        to the legacy in-package rules location if needed.
        """
        candidates = [
            Path(__file__).resolve().parents[2] / "rules" / "vulnerability_rules.json",
            Path(__file__).resolve().parents[1] / "rules" / "vulnerability_rules.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        # If nothing exists, return the primary expected path so the loader raises a clear error.
        return candidates[0]

    def _load_rules(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Rules file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        compiled = []
        for rule in data:
            try:
                regex = re.compile(rule["pattern"], re.IGNORECASE)
            except re.error as exc:
                # Skip invalid rules but continue loading others
                continue
            compiled.append(
                {
                    "name": rule["name"],
                    "category": rule["category"],
                    "severity": rule["severity"],
                    "description": rule["description"],
                    "remediation": rule["remediation"],
                    "cwe_reference": rule.get("cwe_reference"),
                    "regex": regex,
                }
            )
        return compiled

    def scan(self, content: str, file_name: str) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        lines = content.splitlines()
        for rule in self.rules:
            regex = rule["regex"]
            for idx, line in enumerate(lines, start=1):
                if regex.search(line):
                    findings.append(
                        {
                            "name": rule["name"],
                            "severity": rule["severity"],
                            "file_name": Path(file_name).name,
                            "line_number": idx,
                            "description": rule["description"],
                            "remediation": rule["remediation"],
                            "cwe_reference": rule["cwe_reference"],
                            "code_snippet": line.strip(),
                            "category": rule["category"],
                        }
                    )
        return findings
