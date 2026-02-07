"""
A/B Testing scaffold.
Manages variant selection, result recording, and basic reporting.
"""
import json
import time
import random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AB_LOG_DIR, ENABLE_AB_TESTING
from .logger import logger


@dataclass
class ABTestResult:
    """Recorded outcome of an A/B test variant."""
    test_name: str
    variant: str
    query: str
    latency_ms: float
    llm_calls: int
    cost_estimate: float
    success: bool
    quality_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ABTestManager:
    """
    Simple A/B test manager.
    - select_variant(): round-robin or seeded random
    - record_result(): append to JSONL log
    - generate_report(): aggregate stats per variant
    """

    # Define available tests and their variants
    TESTS = {
        "notice_extraction": ["regex_only", "regex_llm_all", "regex_llm_selective"],
        "query_routing": ["heuristic_only", "heuristic_embedding", "heuristic_llm"],
        "sql_summary": ["always_summarize", "lazy_summary"],
        "timeline_answer": ["pattern_only", "llm_synthesis"],
    }

    def __init__(self):
        self._counters: Dict[str, int] = {}

    def select_variant(self, test_name: str, seed: Optional[str] = None) -> str:
        """
        Select a variant for a test.
        Uses round-robin by default, or seeded random if seed provided.
        """
        if not ENABLE_AB_TESTING:
            # Return first variant (control) when A/B testing is off
            variants = self.TESTS.get(test_name, ["control"])
            return variants[0]

        variants = self.TESTS.get(test_name, ["control"])

        if seed:
            rng = random.Random(seed)
            return rng.choice(variants)

        # Round-robin
        count = self._counters.get(test_name, 0)
        variant = variants[count % len(variants)]
        self._counters[test_name] = count + 1
        return variant

    def record_result(self, result: ABTestResult):
        """Append result to JSONL log."""
        if not ENABLE_AB_TESTING:
            return

        log_path = Path(AB_LOG_DIR) / f"{result.test_name}.jsonl"
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[ABTest] Could not write result: {e}")

    def generate_report(self, test_name: str) -> Dict[str, Any]:
        """Generate aggregate stats for a test."""
        log_path = Path(AB_LOG_DIR) / f"{test_name}.jsonl"
        if not log_path.exists():
            return {"test_name": test_name, "error": "No results found"}

        results_by_variant: Dict[str, List[ABTestResult]] = {}
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        variant = data['variant']
                        if variant not in results_by_variant:
                            results_by_variant[variant] = []
                        results_by_variant[variant].append(data)
        except Exception as e:
            return {"test_name": test_name, "error": str(e)}

        report = {"test_name": test_name, "variants": {}}
        for variant, results in results_by_variant.items():
            n = len(results)
            avg_latency = sum(r['latency_ms'] for r in results) / n if n else 0
            avg_cost = sum(r['cost_estimate'] for r in results) / n if n else 0
            avg_llm = sum(r['llm_calls'] for r in results) / n if n else 0
            success_rate = sum(1 for r in results if r['success']) / n if n else 0
            scores = [r['quality_score'] for r in results if r.get('quality_score') is not None]
            avg_quality = sum(scores) / len(scores) if scores else None

            report["variants"][variant] = {
                "count": n,
                "avg_latency_ms": round(avg_latency, 1),
                "avg_cost": round(avg_cost, 6),
                "avg_llm_calls": round(avg_llm, 1),
                "success_rate": round(success_rate, 3),
                "avg_quality_score": round(avg_quality, 3) if avg_quality else None,
            }

        return report


# Singleton
_ab_manager: Optional[ABTestManager] = None


def get_ab_manager() -> ABTestManager:
    global _ab_manager
    if _ab_manager is None:
        _ab_manager = ABTestManager()
    return _ab_manager
