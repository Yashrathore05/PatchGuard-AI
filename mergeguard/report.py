"""
mergeguard/report.py — Validation Report Generator

Formats pipeline results into human-readable markdown reports.
"""

from mergeguard.pipeline import PipelineResult


class ReportGenerator:
    """Generates formatted validation reports from pipeline results."""
    
    @staticmethod
    def generate_markdown(result: PipelineResult) -> str:
        """Generate a full markdown validation report."""
        lines = []
        plan = result.plan
        risk = result.risk
        
        # Header
        lines.append(f"# MergeGuard Validation Report")
        lines.append(f"**Issue #{plan.issue_id}** — {plan.issue_summary}")
        lines.append(f"**Generated:** {plan.timestamp} | **Duration:** {result.total_duration_ms}ms")
        lines.append("")
        
        # Risk Badge
        badge_color = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")
        lines.append(f"## {badge_color} Risk Assessment: {risk.risk_level.upper()}")
        lines.append(f"- **Confidence:** {risk.confidence_score:.0%}")
        lines.append(f"- **Risk Score:** {risk.risk_score:.0%}")
        lines.append(f"- **Recommendation:** {risk.recommendation}")
        lines.append("")
        
        # Plan Summary
        lines.append("## 📋 Implementation Plan")
        lines.append(f"**Root Cause:** {plan.root_cause_analysis}")
        lines.append(f"**Strategy:** {plan.implementation_strategy}")
        lines.append(f"**Complexity:** {plan.estimated_complexity}")
        lines.append(f"**Affected Files:** {', '.join(plan.affected_files)}")
        lines.append("")
        lines.append("| Step | Description | Target | Priority |")
        lines.append("|------|-------------|--------|----------|")
        for step in plan.steps:
            lines.append(f"| {step.step_id} | {step.description} | `{step.file_target}` | {step.priority} |")
        lines.append("")
        
        # Candidate Solutions
        lines.append(f"## 🔧 Candidate Solutions ({len(result.solutions)})")
        for sol in result.solutions:
            rec = " ⭐ RECOMMENDED" if sol.solution_id == result.recommended_solution_id else ""
            lines.append(f"### {sol.solver_name}{rec}")
            lines.append(f"- **ID:** `{sol.solution_id}`")
            lines.append(f"- **Confidence:** {sol.confidence:.0%}")
            lines.append(f"- **Approach:** {sol.approach_description}")
            lines.append(f"- **Generation Time:** {sol.generation_time_ms}ms")
            lines.append(f"```diff\n{sol.patch}\n```")
            lines.append("")
        
        # Test Results
        passed = sum(1 for t in result.test_results if t.passed)
        total = len(result.test_results)
        lines.append(f"## 🧪 Test Results ({passed}/{total} passed)")
        lines.append("| Test | Solution | Status | Output |")
        lines.append("|------|----------|--------|--------|")
        for tr in result.test_results:
            status = "✅" if tr.passed else "❌"
            sid = tr.solution_id[:6]
            lines.append(f"| `{tr.test_id}` | `{sid}` | {status} | {tr.output} |")
        lines.append("")
        
        # Review Results
        lines.append(f"## 🔍 Code Review")
        for review in result.reviews:
            lines.append(f"### Solution `{review.solution_id[:6]}`")
            lines.append(f"| Dimension | Score |")
            lines.append(f"|-----------|-------|")
            lines.append(f"| Security | {review.security_score:.0%} |")
            lines.append(f"| Performance | {review.performance_score:.0%} |")
            lines.append(f"| Maintainability | {review.maintainability_score:.0%} |")
            lines.append(f"| Correctness | {review.correctness_score:.0%} |")
            lines.append(f"| **Overall** | **{review.overall_score:.0%}** |")
            lines.append("")
            if review.findings:
                lines.append("**Findings:**")
                for f in review.findings:
                    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(f.severity, "⚪")
                    lines.append(f"- {sev_icon} **[{f.category.upper()}]** {f.title}: {f.description}")
                lines.append("")
        
        # Risk Factors
        lines.append("## ⚠️ Risk Factors")
        for rf in risk.risk_factors:
            lines.append(f"- {rf}")
        lines.append("")
        
        # Timeline
        lines.append("## ⏱️ Execution Timeline")
        lines.append("| Time | Agent | Action | Status | Duration |")
        lines.append("|------|-------|--------|--------|----------|")
        for ev in result.timeline:
            status_icon = {"completed": "✅", "running": "⏳", "failed": "❌"}.get(ev.status, "⚪")
            lines.append(f"| {ev.timestamp} | {ev.agent} | {ev.action} | {status_icon} | {ev.duration_ms}ms |")
        lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def generate_summary(result: PipelineResult) -> dict:
        """Generate a JSON-serializable summary."""
        risk = result.risk
        plan = result.plan
        return {
            "issue_id": plan.issue_id,
            "issue_summary": plan.issue_summary,
            "complexity": plan.estimated_complexity,
            "num_solutions": len(result.solutions),
            "tests_passed": sum(1 for t in result.test_results if t.passed),
            "tests_total": len(result.test_results),
            "confidence": risk.confidence_score,
            "risk_score": risk.risk_score,
            "risk_level": risk.risk_level,
            "recommendation": risk.recommendation,
            "recommended_solution": result.recommended_solution_id,
            "duration_ms": result.total_duration_ms,
        }
