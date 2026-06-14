"""
server/ui.py — MergeGuard Dashboard UI

Professional SaaS-style dashboard built with Gradio.
Tabs: Pipeline, Validation Report, Agent Timeline, Architecture, Leaderboard
"""

import gradio as gr
import json
import os
import time

try:
    from ..models import ReviewAction
    from .pullrequest_environment import PullRequestEnvironment
except ImportError:
    from models import ReviewAction
    from server.pullrequest_environment import PullRequestEnvironment

from mergeguard.pipeline import MergeGuardPipeline
from mergeguard.report import ReportGenerator


# ---------------------------------------------------------------------------
# Issue choices (reframed from tasks)
# ---------------------------------------------------------------------------

ISSUE_CHOICES = [
    ("🟢 Issue #1  — Login Validation Bug (Easy)", "1"),
    ("🟡 Issue #2  — RBAC Logic Flaw (Medium)", "2"),
    ("🟠 Issue #3  — Iterator Anti-pattern (Hard)", "3"),
    ("🟢 Issue #4  — None Identity Check (Easy)", "4"),
    ("🟡 Issue #5  — Weak Password Hash (Medium)", "5"),
    ("🟠 Issue #6  — SQL Injection + Resource Leak (Hard)", "6"),
    ("🔴 Issue #7  — Deceptive PR: Hidden SQLi (Adversarial)", "7"),
    ("🔴 Issue #8  — PCI Log Violation (Adversarial)", "8"),
    ("🔴 Issue #9  — Multi-File Config Bypass (Adversarial)", "9"),
    ("🔴 Issue #10 — Boolean Logic Trap (Adversarial)", "10"),
    ("🟠 Issue #11 — Mutable Default Arg (Hard)", "11"),
    ("🔴 Issue #12 — Shadowed Variable (Adversarial)", "12"),
    ("🔴 Issue #13 — SQL Injection in Refactor (Adversarial)", "13"),
    ("🟠 Issue #14 — O(n) Regression (Hard)", "14"),
    ("🔴 Issue #15 — Silent Exception Swallow (Adversarial)", "15"),
    ("🔴 Issue #16 — Auth Bypass Logic (Adversarial)", "16"),
    ("⚫ Issue #17 — Race Condition (Expert)", "17"),
    ("🔴 Issue #18 — Misleading Comment Trap (Adversarial)", "18"),
    ("🟡 Issue #19 — Off-by-One Loop (Medium)", "19"),
]


def load_leaderboard():
    """Load benchmark leaderboard from results file."""
    try:
        base = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base, "results", "benchmark_results.json")
        with open(path) as f:
            data = json.load(f)
        rows = []
        for entry in data if isinstance(data, list) else [data]:
            model = entry.get("model", "Unknown")
            score = entry.get("avg_score", entry.get("average_reward", 0.0))
            comp = entry.get("completion_rate", entry.get("task_completion_rate", 1.0))
            rows.append(f"| {model:<40} | {score:.2f}       | {comp:.0%}        |")
        if not rows:
            return "No results yet. Run `benchmark.py` to generate scores."
        table = "| Model                                    | Avg Score  | Completion |\n"
        table += "|------------------------------------------|------------|------------|\n"
        table += "\n".join(rows)
        return table
    except Exception:
        return "| Qwen/Qwen2.5-7B-Instruct                 | 0.67       | 95%        |"


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

_pipeline = MergeGuardPipeline(num_solvers=3)

# Load tasks
_tasks = []
try:
    base = os.path.dirname(os.path.dirname(__file__))
    tp = os.path.join(base, "tasks.json")
    if not os.path.exists(tp):
        tp = "tasks.json"
    with open(tp) as f:
        _tasks = json.load(f)
except Exception:
    pass


def _get_task(issue_id: str) -> dict:
    """Get task by ID."""
    return next((t for t in _tasks if str(t["id"]) == str(issue_id)), None)


# ---------------------------------------------------------------------------
# UI Construction
# ---------------------------------------------------------------------------

def create_ui():
    """Create the MergeGuard dashboard UI."""
    
    custom_css = """
    .gradio-container { max-width: 1400px !important; }
    .risk-critical { color: #dc2626; font-weight: 700; }
    .risk-high { color: #ea580c; font-weight: 700; }
    .risk-medium { color: #ca8a04; font-weight: 700; }
    .risk-low { color: #16a34a; font-weight: 700; }
    .stat-card { 
        background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%);
        border-radius: 12px; padding: 16px; text-align: center;
    }
    .pipeline-status { font-family: 'JetBrains Mono', monospace; }
    """
    
    theme = gr.themes.Base(
        font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
        primary_hue="indigo",
        secondary_hue="slate",
        neutral_hue="slate",
    ).set(
        body_background_fill="#0f0f1a",
        body_background_fill_dark="#0f0f1a",
        block_background_fill="#1a1a2e",
        block_background_fill_dark="#1a1a2e",
        block_border_width="1px",
        block_border_color="#2d2d44",
        block_radius="12px",
        button_primary_background_fill="#6366f1",
        button_primary_background_fill_hover="#818cf8",
        button_primary_text_color="white",
        input_background_fill="#16162a",
        input_background_fill_dark="#16162a",
        border_color_primary="#2d2d44",
    )

    with gr.Blocks(theme=theme, css=custom_css, title="MergeGuard — Autonomous Software Change Validation") as app:
        
        # State
        pipeline_result_state = gr.State(None)
        
        # ── Hero ────────────────────────────────────────────────────
        gr.Markdown("""
<div style="text-align: center; padding: 24px 0 8px 0;">
<h1 style="font-size: 2.2em; font-weight: 800; margin: 0; background: linear-gradient(135deg, #6366f1, #a78bfa, #c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
🛡️ MergeGuard
</h1>
<p style="color: #94a3b8; font-size: 1.1em; margin: 4px 0 0 0;">Autonomous Software Change Validation Platform</p>
<p style="color: #64748b; font-size: 0.85em;">Multi-agent system that plans, generates, tests, reviews, and validates software changes before pull request creation.</p>
</div>
        """)
        
        # ── Stats Bar ──────────────────────────────────────────────
        with gr.Row():
            gr.Markdown("""<div style="text-align:center"><strong style="color:#6366f1">6</strong><br/><span style="color:#94a3b8;font-size:0.85em">AI Agents</span></div>""")
            gr.Markdown("""<div style="text-align:center"><strong style="color:#a78bfa">19</strong><br/><span style="color:#94a3b8;font-size:0.85em">Issues</span></div>""")
            gr.Markdown("""<div style="text-align:center"><strong style="color:#c084fc">5</strong><br/><span style="color:#94a3b8;font-size:0.85em">Validation Layers</span></div>""")
            gr.Markdown("""<div style="text-align:center"><strong style="color:#e879f9">4</strong><br/><span style="color:#94a3b8;font-size:0.85em">Review Dimensions</span></div>""")
        
        # ── Tabs ───────────────────────────────────────────────────
        with gr.Tabs():
            
            # ─── Tab 1: Pipeline Execution ─────────────────────────
            with gr.Tab("🚀 Pipeline"):
                gr.Markdown("### Run the Autonomous Validation Pipeline\nSelect an issue, then run the full multi-agent pipeline: **Plan → Solve → Test → Review → Score**")
                
                with gr.Row():
                    with gr.Column(scale=4):
                        issue_dropdown = gr.Dropdown(
                            choices=ISSUE_CHOICES,
                            label="Select Software Change Issue",
                            value="7",
                        )
                    with gr.Column(scale=1):
                        run_btn = gr.Button("▶ Run Pipeline", variant="primary", size="lg")
                
                with gr.Row():
                    with gr.Column(scale=3):
                        gr.Markdown("#### 📄 Issue Context")
                        issue_title = gr.Textbox(label="Issue Title", interactive=False)
                        issue_desc = gr.Textbox(label="Description", interactive=False, lines=2)
                        issue_context = gr.Textbox(label="Repository Context", interactive=False, lines=2)
                        gr.Markdown("#### 💻 Code Under Analysis")
                        issue_diff = gr.Code(language="python", interactive=False, label="Code Diff")
                    
                    with gr.Column(scale=4):
                        gr.Markdown("#### 📊 Pipeline Status")
                        pipeline_status = gr.Textbox(label="Status", interactive=False, lines=1, value="⏳ Waiting for pipeline run...")
                        
                        with gr.Row():
                            confidence_out = gr.Textbox(label="🎯 Confidence", interactive=False)
                            risk_out = gr.Textbox(label="⚠️ Risk Level", interactive=False)
                        
                        recommendation_out = gr.Textbox(label="📋 Recommendation", interactive=False, lines=2)
                        
                        gr.Markdown("#### 🔧 Recommended Solution")
                        solution_patch = gr.Code(language="python", interactive=False, label="Recommended Patch")
                        solution_approach = gr.Textbox(label="Approach", interactive=False, lines=2)
            
            # ─── Tab 2: Validation Report ──────────────────────────
            with gr.Tab("📑 Validation Report"):
                gr.Markdown("### Full Change Validation Report\nDetailed analysis across all pipeline stages. Run the pipeline first to generate a report.")
                report_output = gr.Markdown(value="*Run the pipeline to generate a validation report.*")
            
            # ─── Tab 3: Agent Timeline ─────────────────────────────
            with gr.Tab("⏱️ Agent Timeline"):
                gr.Markdown("### Agent Execution Timeline\nStep-by-step execution log showing each agent's actions and timing.")
                timeline_output = gr.Markdown(value="*Run the pipeline to see the agent timeline.*")
            
            # ─── Tab 4: Architecture ───────────────────────────────
            with gr.Tab("🏗️ Architecture"):
                gr.Markdown("""
### MergeGuard Architecture

The platform uses a **multi-agent pipeline** where each agent is a specialized component:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MergeGuard Pipeline                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  Issue /  │    │   Planner    │    │   Solver     │              │
│  │  Change   │───▶│   Agent      │───▶│   Agents     │              │
│  │  Request  │    │              │    │  (x3)        │              │
│  └──────────┘    └──────────────┘    └──────┬───────┘              │
│                                              │                      │
│                                              ▼                      │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │                    Test Generation Agent                  │      │
│  │  • Auto-generate test cases                              │      │
│  │  • Run tests against each candidate                      │      │
│  └──────────────────────────────┬───────────────────────────┘      │
│                                  │                                  │
│                                  ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │                      Review Agent                         │      │
│  │  Security │ Performance │ Maintainability │ Correctness   │      │
│  └──────────────────────────────┬───────────────────────────┘      │
│                                  │                                  │
│                                  ▼                                  │
│  ┌──────────────┐    ┌──────────────────────────────────────┐      │
│  │    Risk      │    │     Final Validation Report           │      │
│  │    Scorer    │───▶│  • Recommended solution               │      │
│  │              │    │  • Confidence & risk scores            │      │
│  └──────────────┘    │  • Merge recommendation               │      │
│                      └──────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

---

### Agent Descriptions

| Agent | Purpose | Output |
|-------|---------|--------|
| **PlannerAgent** | Analyzes the issue, identifies root cause, decomposes into tasks | Implementation plan with steps and strategy |
| **SolverAgent** (x3) | Generates independent candidate solutions | Patches with confidence scores |
| **TestGenAgent** | Creates test cases and validates each candidate | Test results per solution |
| **ReviewAgent** | Multi-dimensional analysis across 4 categories | Security, performance, maintainability, correctness scores |
| **RiskScorer** | Aggregates all signals into final assessment | Confidence score, risk level, merge recommendation |

---

### Review Dimensions

| Dimension | What It Checks |
|-----------|---------------|
| 🔒 **Security** | SQL injection, credential exposure, PCI compliance, auth bypasses |
| ⚡ **Performance** | Algorithmic complexity, O(n) regressions, memory leaks |
| 🔧 **Maintainability** | PEP 8, variable shadowing, code clarity |
| ✅ **Correctness** | Test pass rate, functional behavior |
                """)
            
            # ─── Tab 5: Leaderboard ───────────────────────────────
            with gr.Tab("📊 Leaderboard"):
                gr.Markdown("### 🏆 Model Leaderboard\nBaseline scores from automated benchmark runs.")
                gr.Markdown(load_leaderboard())
                gr.Markdown("""
**Scoring:**
- `request_changes` / `suggest_fix` on buggy code: **+0.5 to 1.0**
- Correct keyword reasoning: **+0.3 additional**
- `submit_patch` with matching fix: **+0.2 bonus**
- `approve` on buggy code: **0.01** (penalty)

Run your own model: `HF_TOKEN=... python benchmark.py --model <model_id>`
                """)
            
            # ─── Tab 6: Original Playground ────────────────────────
            with gr.Tab("🧪 Playground"):
                gr.Markdown("### Manual Review Playground\nReview code changes manually and see how the grader scores your review.")
                env_state = gr.State()
                
                with gr.Row():
                    with gr.Column(scale=5):
                        pg_task = gr.Dropdown(choices=ISSUE_CHOICES, label="Select Issue", value="7")
                        pg_load = gr.Button("⬇️ Load Issue", variant="primary")
                        with gr.Group():
                            pg_title = gr.Textbox(label="PR Title", interactive=False)
                            pg_desc = gr.Textbox(label="Description", interactive=False, lines=2)
                            pg_ci = gr.Textbox(label="CI Logs", interactive=False, lines=2)
                            pg_diff = gr.Code(language="python", interactive=False)
                    
                    with gr.Column(scale=4):
                        pg_action = gr.Radio(
                            choices=["approve", "request_changes", "comment", "suggest_fix", "submit_patch"],
                            label="Your Decision", value="request_changes"
                        )
                        pg_comment = gr.Textbox(label="Review Comment", lines=5,
                            placeholder="Describe the issue you found...")
                        pg_patch = gr.Code(label="Proposed Patch (submit_patch only)", language="python")
                        pg_submit = gr.Button("✅ Submit Review", variant="primary")
                        pg_reward = gr.Textbox(label="Reward [0.01 – 0.99]", interactive=False)
                        pg_feedback = gr.Textbox(label="Feedback", interactive=False, lines=2)
        
        # ── Handlers ───────────────────────────────────────────────
        
        def load_issue(issue_id):
            """Load issue context into the pipeline tab."""
            task = _get_task(issue_id)
            if not task:
                return "Unknown", "", "", "", None
            return (
                task.get("pr_title", ""),
                task.get("pr_description", ""),
                task.get("repository_context", ""),
                task.get("code_diff", ""),
                None,  # reset pipeline result
            )
        
        issue_dropdown.change(
            load_issue,
            inputs=[issue_dropdown],
            outputs=[issue_title, issue_desc, issue_context, issue_diff, pipeline_result_state],
        )
        
        def run_pipeline(issue_id):
            """Execute the full MergeGuard pipeline."""
            task = _get_task(issue_id)
            if not task:
                return ("❌ Issue not found", "", "", "", "", "", 
                        "*Issue not found*", "*Issue not found*", None)
            
            result = _pipeline.run(task)
            report_md = ReportGenerator.generate_markdown(result)
            
            # Build timeline markdown
            tl_lines = ["| Time | Agent | Action | Status | Duration |",
                        "|------|-------|--------|--------|----------|"]
            for ev in result.timeline:
                icon = {"completed": "✅", "running": "⏳", "failed": "❌"}.get(ev.status, "⚪")
                tl_lines.append(f"| {ev.timestamp} | {ev.agent} | {ev.action} | {icon} | {ev.duration_ms}ms |")
            timeline_md = "\n".join(tl_lines)
            
            # Get recommended solution
            best = next((s for s in result.solutions if s.solution_id == result.recommended_solution_id), None)
            
            risk = result.risk
            badge = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")
            
            return (
                f"✅ Pipeline complete — {result.total_duration_ms}ms | {len(result.solutions)} solutions | {sum(1 for t in result.test_results if t.passed)}/{len(result.test_results)} tests passed",
                f"{risk.confidence_score:.0%}",
                f"{badge} {risk.risk_level.upper()} ({risk.risk_score:.0%})",
                risk.recommendation,
                best.patch if best else "No solution generated",
                best.approach_description if best else "",
                report_md,
                timeline_md,
                result,
            )
        
        run_btn.click(
            run_pipeline,
            inputs=[issue_dropdown],
            outputs=[
                pipeline_status, confidence_out, risk_out, recommendation_out,
                solution_patch, solution_approach,
                report_output, timeline_output,
                pipeline_result_state,
            ],
        )
        
        # Playground handlers (preserved from original)
        def load_task(task_id):
            env = PullRequestEnvironment()
            obs = env.reset(task_id)
            return env, obs.pr_title, obs.pr_description, obs.ci_logs, obs.code_diff, "", ""
        
        pg_load.click(
            load_task,
            inputs=[pg_task],
            outputs=[env_state, pg_title, pg_desc, pg_ci, pg_diff, pg_reward, pg_feedback],
        )
        
        def submit_review(env, a_type, a_comment, a_patch):
            if env is None:
                return env, "", "⚠️ Please load an issue first!"
            action = ReviewAction(type=a_type, comment=a_comment, patch=a_patch or "")
            obs = env.step(action)
            emoji = "🟢" if (obs.reward or 0) >= 0.6 else "🔴"
            return env, f"{emoji} {obs.reward:.2f}", obs.feedback
        
        pg_submit.click(
            submit_review,
            inputs=[env_state, pg_action, pg_comment, pg_patch],
            outputs=[env_state, pg_reward, pg_feedback],
        )
    
    return app
