import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import ReviewAction, PRObservation
from server.pullrequest_environment import PullRequestEnvironment
from server.graders import route_grader

def test_reset_returns_valid_observation():
    env = PullRequestEnvironment()
    obs = env.reset()
    assert obs.pr_title != ""
    assert obs.code_diff != ""
    assert obs.done is False

def test_step_correct_action_task_1():
    env = PullRequestEnvironment()
    env.reset("1")
    action = ReviewAction(type="request_changes", comment="== comparison operator")
    next_obs = env.step(action)
    assert next_obs.reward >= 0.6

def test_step_wrong_action_gets_low_score():
    env = PullRequestEnvironment()
    env.reset("1")
    action = ReviewAction(type="approve", comment="looks good")
    next_obs = env.step(action)
    assert next_obs.reward <= 0.1

def test_deceptive_pr_task_7():
    env = PullRequestEnvironment()
    env.reset("7")
    action = ReviewAction(type="approve", comment="looks fine, just a typo")
    next_obs = env.step(action)
    assert next_obs.reward == 0.01

def test_all_9_tasks_load():
    env = PullRequestEnvironment()
    for task_id in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        obs = env.reset(task_id)
        assert obs.pr_title != ""
        assert obs.code_diff != ""
        assert str(obs.task_id) == str(task_id)

def test_mergeguard_pipeline():
    from mergeguard.pipeline import MergeGuardPipeline
    from mergeguard.agents import PlannerAgent, SolverAgent, TestGenAgent, ReviewAgent, RiskScorer
    
    # Init pipeline
    pipeline = MergeGuardPipeline(num_solvers=3)
    
    # Test on Task 7
    env = PullRequestEnvironment()
    obs = env.reset("7")
    task = env.current_task
    
    result = pipeline.run(task)
    assert result.issue_id == "7"
    assert result.plan is not None
    assert len(result.solutions) == 3
    assert len(result.test_cases) > 0
    assert len(result.test_results) > 0
    assert len(result.reviews) == 3
    assert result.risk is not None
    assert result.risk.risk_level in ["low", "medium", "high", "critical"]
    assert result.recommended_solution_id != ""
    assert len(result.timeline) > 0
    
    # Verify report markdown generation
    from mergeguard.report import ReportGenerator
    report = ReportGenerator.generate_markdown(result)
    assert "# MergeGuard Validation Report" in report
    assert "Risk Assessment" in report
    assert "Implementation Plan" in report
    assert "Candidate Solutions" in report
    assert "Test Results" in report
    assert "Execution Timeline" in report

def test_patchguard_pipeline():
    from patchguard.pipeline import PatchGuardPipeline
    from patchguard.agents import (
        RepositoryScannerAgent, PlannerAgent, SolverAgent,
        TestGenerationAgent, ValidationAgent, ReviewAgent,
        RiskScoringAgent, ReportAgent
    )
    
    # Init pipeline
    pipeline = PatchGuardPipeline(num_solvers=3)
    
    # Test on Task 7
    env = PullRequestEnvironment()
    obs = env.reset("7")
    task = env.current_task
    
    # Context mock
    context = {
        "repo_url": "https://github.com/demo-user/demo-repo",
        "clone_dir": "",
        "is_demo": True,
        "github_token": None
    }
    
    result = pipeline.run(task, context)
    assert result.issue_id == "7"
    assert result.plan is not None
    assert len(result.solutions) == 3
    assert len(result.test_cases) > 0
    assert len(result.test_results) > 0
    assert len(result.reviews) == 3
    assert result.risk is not None
    assert result.risk.risk_level in ["low", "medium", "high", "critical"]
    assert result.recommended_solution_id != ""
    assert len(result.timeline) > 0
    assert result.scanner_output is not None
    assert result.scanner_output["framework"] == "FastAPI" # Since task 7 language is python
    
    # Verify report markdown generation
    from patchguard.report import ReportGenerator
    report = ReportGenerator.generate_markdown(result)
    assert "# PatchGuard AI Validation Report" in report
    assert "Repository Analysis" in report
    assert "Risk Assessment" in report
    assert "Implementation Plan" in report
    assert "Candidate Solutions" in report
    assert "Test Results" in report
    assert "Execution Timeline" in report


def test_patch_application_agent_modifies_real_files(tmp_path):
    from patchguard.agents import PatchApplicationAgent
    
    # 1. Create a dummy file in a temp directory
    target_file = tmp_path / "hello.py"
    target_file.write_text("def hello():\n    print('Hello World')\n")
    
    # 2. Define a unified diff patch
    patch = """--- hello.py
+++ hello.py
@@ -1,2 +1,2 @@
 def hello():
-    print('Hello World')
+    print('Hello PatchGuard')
"""
    
    # 3. Apply patch
    applier = PatchApplicationAgent()
    success = applier.apply_patch(patch, str(tmp_path))
    
    # 4. Verify modified content
    assert success is True
    modified_content = target_file.read_text()
    assert "Hello PatchGuard" in modified_content
    assert "Hello World" not in modified_content


def test_llm_agents_with_mock_responses():
    from unittest.mock import patch
    from patchguard.agents import PlannerAgent, SolverAgent, TestGenerationAgent, ReviewAgent, Plan
    
    # Mock task and scanner
    task = {
        "id": "1",
        "pr_title": "Fix sql injection",
        "pr_description": "Vulnerable query interpolation",
        "files_changed": ["db.py"],
        "code_diff": "query = f'SELECT * FROM users WHERE id = {user_id}'",
        "difficulty": "medium"
    }
    scanner_output = {
        "language": "Python",
        "framework": "FastAPI",
        "project_structure": {"total_files": 1, "directories": [], "config_files": []}
    }
    
    # 1. Test PlannerAgent with LLM Mock
    mock_plan_json = {
        "root_cause_analysis": "User input interpolated into SQL query",
        "implementation_strategy": "Use parameterized queries",
        "steps": [
            {"step_id": 1, "description": "Update db.py query", "file_target": "db.py", "priority": "critical"}
        ]
    }
    with patch("patchguard.agents.call_llm_json", return_value=mock_plan_json):
        planner = PlannerAgent()
        plan = planner.analyze(task, scanner_output)
        assert plan.root_cause_analysis == "User input interpolated into SQL query"
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "Update db.py query"
        
    # 2. Test SolverAgent with LLM Mock
    mock_sol_json = {
        "patch": "--- db.py\n+++ db.py\n-query = f'SELECT * FROM users WHERE id = {user_id}'\n+query = 'SELECT * FROM users WHERE id = %s'",
        "approach_description": "Parameterized sql statement",
        "confidence": 0.95
    }
    with patch("patchguard.agents.call_llm_json", return_value=mock_sol_json):
        solver = SolverAgent("solver-test")
        sol = solver.solve(task, plan)
        assert "SELECT * FROM users" in sol.patch
        assert sol.confidence == 0.95
        assert sol.solver_name == "solver-test"
        
    # 3. Test TestGenerationAgent with LLM Mock
    mock_test_json = {
        "test_cases": [
            {
                "test_id": "test-sql-1",
                "test_name": "test_sql_parameterized",
                "test_code": "assert '%s' in query",
                "target_function": "execute_query",
                "test_type": "unit"
            }
        ]
    }
    with patch("patchguard.agents.call_llm_json", return_value=mock_test_json):
        tester = TestGenerationAgent()
        tests = tester.generate_tests(task)
        assert len(tests) == 1
        assert tests[0].test_id == "test-sql-1"
        assert tests[0].test_code == "assert '%s' in query"
        
    # 4. Test ReviewAgent with LLM Mock
    mock_review_json = {
        "security_score": 0.95,
        "performance_score": 0.9,
        "maintainability_score": 0.85,
        "correctness_score": 1.0,
        "overall_score": 0.93,
        "findings": [
            {
                "category": "security",
                "severity": "critical",
                "title": "SQL Injection fixed",
                "description": "Validated query parameters",
                "line_reference": "",
                "recommendation": "Merge solution"
            }
        ]
    }
    from patchguard.agents import TestResult
    test_results = [TestResult("test-sql-1", sol.solution_id, True, "PASS", 10)]
    with patch("patchguard.agents.call_llm_json", return_value=mock_review_json):
        reviewer = ReviewAgent()
        review = reviewer.review(sol, task, test_results)
        assert review.security_score == 0.95
        assert review.overall_score == 0.93
        assert len(review.findings) == 1
        assert review.findings[0].category == "security"


