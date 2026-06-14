"""
mergeguard/pipeline.py — End-to-end orchestration of the MergeGuard agent pipeline.

Workflow:
    Issue → PlannerAgent → SolverAgents → TestGenAgent → ReviewAgent → RiskScorer → Report
"""

import time
from dataclasses import dataclass, field
from mergeguard.agents import (
    PlannerAgent, SolverAgent, TestGenAgent, ReviewAgent, RiskScorer,
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
    """Complete output of a MergeGuard pipeline run."""
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


class MergeGuardPipeline:
    """
    Orchestrates the full MergeGuard validation pipeline.
    
    Executes agents in sequence:
    1. PlannerAgent analyzes the issue
    2. Multiple SolverAgents generate candidate solutions
    3. TestGenAgent creates and runs tests
    4. ReviewAgent analyzes each candidate
    5. RiskScorer produces final assessment
    """
    
    def __init__(self, num_solvers: int = 3):
        self.planner = PlannerAgent()
        self.solvers = [
            SolverAgent(f"solver-{name}")
            for name in ["alpha", "beta", "gamma"][:num_solvers]
        ]
        self.tester = TestGenAgent()
        self.reviewer = ReviewAgent()
        self.risk_scorer = RiskScorer()
    
    def run(self, task: dict) -> PipelineResult:
        """Execute the full pipeline for a given task/issue."""
        pipeline_start = time.time()
        issue_id = str(task.get("id", "0"))
        timeline = []
        
        def _event(agent: str, action: str, status: str, duration: int = 0, details: str = ""):
            timeline.append(PipelineEvent(
                timestamp=time.strftime("%H:%M:%S"),
                agent=agent, action=action, status=status,
                duration_ms=duration, details=details,
            ))
        
        # Stage 1: Planning
        _event("PlannerAgent", "Analyzing issue", "running")
        t0 = time.time()
        plan = self.planner.analyze(task)
        d = int((time.time() - t0) * 1000)
        _event("PlannerAgent", "Plan generated", "completed", d,
               f"{len(plan.steps)} steps, complexity: {plan.estimated_complexity}")
        
        # Stage 2: Solving
        solutions = []
        for solver in self.solvers:
            _event(f"SolverAgent ({solver.solver_id})", "Generating solution", "running")
            t0 = time.time()
            sol = solver.solve(task, plan)
            d = int((time.time() - t0) * 1000)
            solutions.append(sol)
            _event(f"SolverAgent ({solver.solver_id})", "Solution generated", "completed", d,
                   f"confidence: {sol.confidence:.0%}")
        
        # Stage 3: Test Generation & Execution
        _event("TestGenAgent", "Generating tests", "running")
        t0 = time.time()
        test_cases = self.tester.generate_tests(task)
        d = int((time.time() - t0) * 1000)
        _event("TestGenAgent", f"{len(test_cases)} tests generated", "completed", d)
        
        all_test_results = []
        for sol in solutions:
            _event("TestGenAgent", f"Running tests on {sol.solver_name}", "running")
            t0 = time.time()
            results = self.tester.run_tests(test_cases, sol, task)
            d = int((time.time() - t0) * 1000)
            passed = sum(1 for r in results if r.passed)
            all_test_results.extend(results)
            _event("TestGenAgent", f"Tests complete: {passed}/{len(results)} passed", "completed", d)
        
        # Stage 4: Review
        reviews = []
        for sol in solutions:
            _event("ReviewAgent", f"Reviewing {sol.solver_name}", "running")
            t0 = time.time()
            sol_tests = [r for r in all_test_results if r.solution_id == sol.solution_id]
            review = self.reviewer.review(sol, task, sol_tests)
            d = int((time.time() - t0) * 1000)
            reviews.append(review)
            _event("ReviewAgent", f"Review complete: {review.overall_score:.0%}", "completed", d)
        
        # Stage 5: Risk Scoring
        _event("RiskScorer", "Computing risk assessment", "running")
        t0 = time.time()
        risk = self.risk_scorer.score(plan, solutions, all_test_results, reviews)
        d = int((time.time() - t0) * 1000)
        _event("RiskScorer", f"Risk: {risk.risk_level} ({risk.risk_score:.0%})", "completed", d)
        
        # Select best solution
        best = max(solutions, key=lambda s: s.confidence) if solutions else None
        
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
        )
