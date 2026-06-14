"""
patchguard/report.py — Validation Report Generator
"""

from patchguard.pipeline import PipelineResult
from patchguard.agents import ReportAgent


class ReportGenerator:
    """Generates formatted validation reports from pipeline results."""
    
    @staticmethod
    def generate_markdown(result: PipelineResult) -> str:
        """Generate a full markdown validation report using ReportAgent."""
        agent = ReportAgent()
        return agent.generate_markdown(result)
    
    @staticmethod
    def generate_summary(result: PipelineResult) -> dict:
        """Generate a JSON-serializable summary using ReportAgent."""
        agent = ReportAgent()
        return agent.generate_summary(result)
