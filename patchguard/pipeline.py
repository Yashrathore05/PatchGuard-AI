"""
patchguard/pipeline.py — End-to-end orchestration of the PatchGuard AI validation pipeline.
"""

import time
import subprocess
from dataclasses import dataclass, field
from patchguard.agents import (
    RepositoryScannerAgent, PlannerAgent, SolverAgent, PatchApplicationAgent,
    TestGenerationAgent, ValidationAgent, ReviewAgent, RiskScoringAgent, ReportAgent,
    Plan, CandidateSolution, TestCase, TestResult, ReviewResult, RiskAssessment,
)


@dataclass
class PipelineEvent:
    """A single event in the pipeline execution timeline."""
    timestamp: str
    agent: str
    action: str
    status: str  # running, completed, failed
    duration_ms: int = 0
    details: str = ""


@dataclass
class PipelineResult:
    """Complete output of a PatchGuard pipeline run."""
    issue_id: str
    plan: Plan = None
    solutions: list[CandidateSolution] = field(default_factory=list)
    test_cases: list[TestCase] = field(default_factory=list)
    test_results: list[TestResult] = field(default_factory=list)
    reviews: list[ReviewResult] = field(default_factory=list)
    risk: RiskAssessment = None
    timeline: list[PipelineEvent] = field(default_factory=list)
    total_duration_ms: int = 0
    recommended_solution_id: str = ""
    scanner_output: dict = field(default_factory=dict)


class PatchGuardPipeline:
    """
    Orchestrates the full PatchGuard validation pipeline.
    
    Executes agents in sequence:
    1. RepositoryScannerAgent scans repository layout
    2. PlannerAgent analyzes the issue with scanner context
    3. Multiple SolverAgents generate candidate solutions
    4. TestGenAgent creates tests
    5. For each candidate solution:
       a. Reverts repository to clean state
       b. PatchApplicationAgent applies candidate patch directly
       c. ValidationAgent runs tests on applied changes
       d. ReviewAgent performs security/perf/maint/correctness reviews
    6. Selects recommended solution and permanently applies it
    7. RiskScoringAgent produces final assessment
    """
    
    def __init__(self, num_solvers: int = 3):
        self.scanner = RepositoryScannerAgent()
        self.planner = PlannerAgent()
        self.solvers = [
            SolverAgent(f"solver-{name}")
            for name in ["alpha", "beta", "gamma"][:num_solvers]
        ]
        self.patch_applier = PatchApplicationAgent()
        self.tester = TestGenerationAgent()
        self.validator = ValidationAgent()
        self.reviewer = ReviewAgent()
        self.risk_scorer = RiskScoringAgent()
        self.reporter = ReportAgent()
    
    def run(self, task: dict, context: dict | None = None) -> PipelineResult:
        """Execute the full pipeline for a given task/issue."""
        pipeline_start = time.time()
        issue_id = str(task.get("id", "0"))
        timeline = []
        
        if context is None:
            context = {
                "repo_url": "",
                "clone_dir": "",
                "is_demo": True,
                "github_token": None
            }
        
        is_demo = context.get("is_demo", True)
        clone_dir = context.get("clone_dir", "")
        
        def _event(agent: str, action: str, status: str, duration: int = 0, details: str = ""):
            timeline.append(PipelineEvent(
                timestamp=time.strftime("%H:%M:%S"),
                agent=agent, action=action, status=status,
                duration_ms=duration, details=details,
            ))
            
        # Stage 1: Repository Scanner
        _event("RepositoryScannerAgent", "Scanning repository structure", "running")
        t0 = time.time()
        scanner_output = self.scanner.scan(
            repo_url=context.get("repo_url", ""),
            clone_dir=clone_dir,
            is_demo=is_demo,
            task=task
        )
        d = int((time.time() - t0) * 1000)
        context["scanner_output"] = scanner_output
        _event("RepositoryScannerAgent", "Scan complete", "completed", d,
               f"Language: {scanner_output.get('language')}, Framework: {scanner_output.get('framework')}")
        
        # Stage 2: Planning
        _event("PlannerAgent", "Analyzing issue", "running")
        t0 = time.time()
        plan = self.planner.analyze(task, scanner_output)
        d = int((time.time() - t0) * 1000)
        _event("PlannerAgent", "Plan generated", "completed", d,
               f"{len(plan.steps)} steps, complexity: {plan.estimated_complexity}")
        
        # Stage 3: Solving
        solutions = []
        for solver in self.solvers:
            _event(f"SolverAgent ({solver.solver_id})", "Generating solution", "running")
            t0 = time.time()
            sol = solver.solve(task, plan)
            d = int((time.time() - t0) * 1000)
            solutions.append(sol)
            _event(f"SolverAgent ({solver.solver_id})", "Solution generated", "completed", d,
                   f"confidence: {sol.confidence:.0%}")
        
        # Stage 4: Test Generation
        _event("TestGenerationAgent", "Generating tests", "running")
        t0 = time.time()
        test_cases = self.tester.generate_tests(task)
        d = int((time.time() - t0) * 1000)
        _event("TestGenerationAgent", f"{len(test_cases)} tests generated", "completed", d)
        
        # Stage 5 & 6: Application, Validation & Review
        all_test_results = []
        reviews = []
        
        for sol in solutions:
            # 1. Clean workspace (revert dirty files and clean untracked files)
            if not is_demo and clone_dir:
                subprocess.run(["git", "checkout", "."], cwd=clone_dir, capture_output=True)
                subprocess.run(["git", "clean", "-fd"], cwd=clone_dir, capture_output=True)
                
            # 2. Apply patch using PatchApplicationAgent
            _event("PatchApplicationAgent", f"Applying patch for {sol.solver_name}", "running")
            t_app = time.time()
            applied = self.patch_applier.apply_patch(sol.patch, clone_dir)
            d_app = int((time.time() - t_app) * 1000)
            _event("PatchApplicationAgent", f"Patch applied: {applied}", "completed", d_app)
            
            # 3. Validate tests on applied changes
            _event("ValidationAgent", f"Validating solution {sol.solver_name}", "running")
            t0 = time.time()
            results = self.validator.validate(test_cases, sol, task, context)
            d = int((time.time() - t0) * 1000)
            passed = sum(1 for r in results if r.passed)
            all_test_results.extend(results)
            _event("ValidationAgent", f"Validation complete: {passed}/{len(results)} passed", "completed", d)
            
            # 4. Review the candidate
            _event("ReviewAgent", f"Reviewing {sol.solver_name}", "running")
            t0 = time.time()
            sol_tests = [r for r in results if r.solution_id == sol.solution_id]
            review = self.reviewer.review(
                sol, task, sol_tests,
                clone_dir=clone_dir,
                affected_files=task.get("files_changed", []),
            )
            d = int((time.time() - t0) * 1000)
            reviews.append(review)
            _event("ReviewAgent", f"Review complete: {review.overall_score:.0%}", "completed", d)
            
        # Select best recommended solution based on review score
        best = None
        if solutions:
            sol_scores = {r.solution_id: r.overall_score for r in reviews}
            best = max(solutions, key=lambda s: sol_scores.get(s.solution_id, s.confidence))
            
        # Re-apply the recommended solution permanently to the git repository
        if best and not is_demo and clone_dir:
            subprocess.run(["git", "checkout", "."], cwd=clone_dir, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], cwd=clone_dir, capture_output=True)
            self.patch_applier.apply_patch(best.patch, clone_dir)
            
        # Stage 7: Risk Scoring
        _event("RiskScoringAgent", "Computing risk assessment", "running")
        t0 = time.time()
        risk = self.risk_scorer.score(plan, solutions, all_test_results, reviews)
        d = int((time.time() - t0) * 1000)
        _event("RiskScoringAgent", f"Risk: {risk.risk_level} ({risk.risk_score:.0%})", "completed", d)
        
        total = int((time.time() - pipeline_start) * 1000)
        
        return PipelineResult(
            issue_id=issue_id,
            plan=plan,
            solutions=solutions,
            test_cases=test_cases,
            test_results=all_test_results,
            reviews=reviews,
            risk=risk,
            timeline=timeline,
            total_duration_ms=total,
            recommended_solution_id=best.solution_id if best else "",
            scanner_output=scanner_output,
        )
