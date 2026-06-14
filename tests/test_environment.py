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

