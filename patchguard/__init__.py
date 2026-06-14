"""
PatchGuard AI — Autonomous Software Change Validation Platform

Multi-agent system that analyzes repositories, generates fixes,
validates changes, reviews risk, and creates pull requests.
"""

from patchguard.github_client import GitHubClient
from patchguard.agents import (
    PatchGuardAgent,
    RepositoryScannerAgent,
    PlannerAgent,
    SolverAgent,
    PatchApplicationAgent,
    TestGenerationAgent,
    ValidationAgent,
    ReviewAgent,
    RiskScoringAgent,
    ReportAgent,
)
from patchguard.pipeline import PatchGuardPipeline

__all__ = [
    "GitHubClient",
    "PatchGuardAgent",
    "RepositoryScannerAgent",
    "PlannerAgent",
    "SolverAgent",
    "PatchApplicationAgent",
    "TestGenerationAgent",
    "ValidationAgent",
    "ReviewAgent",
    "RiskScoringAgent",
    "ReportAgent",
    "PatchGuardPipeline",
]
