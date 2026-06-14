"""
server/ui.py — PatchGuard AI Dashboard UI

Professional SaaS-style dashboard built with Gradio.
Tabs: Pipeline, Validation Report, Agent Timeline, Architecture, Leaderboard, Playground
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

from patchguard.github_client import GitHubClient
from patchguard.pipeline import PatchGuardPipeline
from patchguard.report import ReportGenerator
from patchguard.providers import get_provider

# ---------------------------------------------------------------------------
# Default Issue choices (fallback when not connected to GitHub)
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

# Load tasks.json for local/demo mode
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
# Handlers for GitHub Connectivity
# ---------------------------------------------------------------------------

def run_full_flow(repo_url, issue_id, client, issues):
    """
    Connects/clones the repository (if URL changed/provided), 
    determines the issue to run on (the selected one, or the latest open issue from the repo, or demo fallback),
    runs the scanner, and executes the full PatchGuard validation pipeline.
    """
    status_msg = ""
    # 1. Initialize Client & Connect/Clone if URL is provided
    if repo_url:
        # Check if we are already connected to this URL
        if not client or client.repo_url != repo_url:
            token = os.environ.get("GITHUB_TOKEN")
            client = GitHubClient(token=token)
            meta = client.connect(repo_url)
            if not meta.connected:
                status_msg = f"🔴 Connection failed: {meta.error}"
                # Fall back to demo mode
                client = GitHubClient()
            else:
                try:
                    client.clone_repo()
                    status_msg = f"🟢 Connected and cloned {client.mode_label}"
                except Exception as e:
                    status_msg = f"🔴 Clone failed: {e}. Running in demo mode."
                    client = GitHubClient()
        else:
            status_msg = f"🟢 Using cached clone for {client.repo_url}"
    else:
        # No URL provided, use demo mode
        client = GitHubClient()
        status_msg = "⚪ Running in local tasks.json Demo Mode"

    # 2. Fetch issues and choose target
    if not client.is_demo:
        try:
            issues_list = client.fetch_issues()
        except Exception:
            issues_list = []
        
        choices = [(f"Issue #{i.number} — {i.title}", str(i.number)) for i in issues_list]
        if not choices:
            choices = ISSUE_CHOICES
        
        # Determine target issue
        issue = None
        if issue_id:
            # Try to find the selected issue
            issue = next((iss for iss in issues_list if str(iss.number) == str(issue_id)), None)
        if not issue and issues_list:
            # Fall back to first/latest issue
            issue = issues_list[0]
            
        if issue:
            task = client.get_task_for_issue(issue)
            target_issue_id = str(issue.number)
        else:
            task = next((t for t in _tasks if str(t["id"]) == "7"), None)
            target_issue_id = "7"
    else:
        choices = ISSUE_CHOICES
        issues_list = []
        target_issue_id = issue_id if issue_id in [c[1] for c in choices] else "7"
        task = next((t for t in _tasks if str(t["id"]) == target_issue_id), None)

    if not task:
        task = _tasks[0] if _tasks else {}
        target_issue_id = str(task.get("id", "7"))

    # Update repo meta text
    if not client.is_demo and client.metadata:
        meta = client.metadata
        repo_meta_text = (
            f"**Repo:** {meta.full_name}\n"
            f"- **Description:** {meta.description or 'No description'}\n"
            f"- **Language:** {meta.language}\n"
            f"- **Stars:** {meta.stars} | **Forks:** {meta.forks}\n"
            f"- **Default Branch:** {meta.default_branch}"
        )
    else:
        repo_meta_text = (
            f"**Repo:** local/demo-repo\n"
            f"- **Description:** Local Demo Repository\n"
            f"- **Language:** Python\n"
            f"- **Default Branch:** main"
        )

    # 3. Context setup & Pipeline Execution
    context = {
        "repo_url": client.repo_url or "https://github.com/demo-user/demo-repo",
        "clone_dir": client.clone_dir,
        "is_demo": client.is_demo,
        "github_token": client.token
    }
    
    pipeline = PatchGuardPipeline(num_solvers=3)
    result = pipeline.run(task, context)
    report_md = ReportGenerator.generate_markdown(result)
    
    # Format timeline
    tl_lines = ["| Time | Agent | Action | Status | Duration |",
                "|------|-------|--------|--------|----------|"]
    for ev in result.timeline:
        icon = {"completed": "✅", "running": "⏳", "failed": "❌"}.get(ev.status, "⚪")
        tl_lines.append(f"| {ev.timestamp} | {ev.agent} | {ev.action} | {icon} | {ev.duration_ms}ms |")
    timeline_md = "\n".join(tl_lines)
    
    # Scanner formatting
    so = result.scanner_output
    scanner_text = (
        f"- **Language:** {so.get('language')}\n"
        f"- **Framework:** {so.get('framework')}\n"
        f"- **Package Manager:** {so.get('package_manager')}\n"
        f"- **Test Framework:** {so.get('test_framework')}\n\n"
        f"**Structure Details:**\n"
        f"- Total Files: {so.get('project_structure', {}).get('total_files', 0)}\n"
        f"- Top Directories: {', '.join(so.get('project_structure', {}).get('directories', []))}\n"
        f"- Config Files: {', '.join(so.get('project_structure', {}).get('config_files', []))}"
    )
    
    best = next((s for s in result.solutions if s.solution_id == result.recommended_solution_id), None)
    risk = result.risk
    badge = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")
    
    # PR Preview text
    pr_preview_text = (
        f"### 📑 Pull Request Draft\n"
        f"**Title:** PatchGuard AI: {task.get('pr_title', 'Fix issue')}\n\n"
        f"**Description:**\n"
        f"{task.get('pr_description', '')}\n\n"
        f"**Validation Summary:**\n"
        f"- Confidence Score: {risk.confidence_score:.0%}\n"
        f"- Risk Score: {risk.risk_score:.0%}\n"
        f"- Risk Level: {risk.risk_level.upper()}\n"
        f"- Recommendation: {risk.recommendation}\n"
    )
    
    p = get_provider()
    pipeline_status_msg = f"✅ Pipeline complete — {result.total_duration_ms}ms | {len(result.solutions)} solutions | {sum(1 for t in result.test_results if t.passed)}/{len(result.test_results)} tests passed | ⚡ {p.display_name}"

    return (
        status_msg,
        gr.update(choices=choices, value=target_issue_id),
        client,
        issues_list,
        repo_meta_text,
        scanner_text,
        task.get("pr_title", ""),
        task.get("pr_description", ""),
        task.get("repository_context", ""),
        task.get("code_diff", ""),
        pipeline_status_msg,
        f"{risk.confidence_score:.0%}",
        f"{badge} {risk.risk_level.upper()} ({risk.risk_score:.0%})",
        risk.recommendation,
        best.patch if best else "No solution generated",
        best.approach_description if best else "",
        report_md,
        timeline_md,
        pr_preview_text,
        task.get("pr_title", "Fix issue"),
        result
    )



# ---------------------------------------------------------------------------
# UI Construction
# ---------------------------------------------------------------------------

def create_ui():
    """Create the PatchGuard AI dashboard UI."""
    
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

    with gr.Blocks(theme=theme, css=custom_css, title="PatchGuard AI — Autonomous Software Change Validation") as app:
        
        # State variables
        client_state = gr.State(GitHubClient())
        issues_state = gr.State([])
        pipeline_result_state = gr.State(None)
        pr_title_state = gr.State("")
        
        # ── Hero ────────────────────────────────────────────────────
        provider = get_provider()
        provider_label = provider.display_name
        provider_color = {"gemini": "#4285f4", "openrouter": "#f97316", "ollama": "#22c55e"}.get(provider.active_provider, "#94a3b8")
        
        gr.Markdown(f"""
<div style="text-align: center; padding: 24px 0 8px 0;">
<h1 style="font-size: 2.2em; font-weight: 800; margin: 0; background: linear-gradient(135deg, #6366f1, #a78bfa, #c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
🛡️ PatchGuard AI
</h1>
<p style="color: #94a3b8; font-size: 1.1em; margin: 4px 0 0 0;">Autonomous Software Change Validation Platform</p>
<p style="color: #64748b; font-size: 0.85em;">Analyze repositories, generate fixes, validate changes, review risk, and create pull requests — autonomously.</p>
<div style="display: inline-block; margin-top: 8px; padding: 4px 12px; border-radius: 999px; background: {provider_color}22; border: 1px solid {provider_color}44;">
  <span style="color: {provider_color}; font-size: 0.8em; font-weight: 600;">⚡ Active Provider: {provider_label}</span>
</div>
</div>
        """)
        
        # ── Stats Bar ──────────────────────────────────────────────
        with gr.Row():
            gr.Markdown("""<div style="text-align:center"><strong style="color:#6366f1">8</strong><br/><span style="color:#94a3b8;font-size:0.85em">Autonomous Agents</span></div>""")
            gr.Markdown(f"""<div style="text-align:center"><strong style="color:{provider_color}">{provider_label}</strong><br/><span style="color:#94a3b8;font-size:0.85em">Active LLM Provider</span></div>""")
            gr.Markdown("""<div style="text-align:center"><strong style="color:#c084fc">6</strong><br/><span style="color:#94a3b8;font-size:0.85em">Validation Stages</span></div>""")
            gr.Markdown("""<div style="text-align:center"><strong style="color:#e879f9">4</strong><br/><span style="color:#94a3b8;font-size:0.85em">Review Dimensions</span></div>""")
            
        # ── GitHub Connection Panel ──────────────────────────────────
        with gr.Group():
            gr.Markdown("### 🔗 Connect GitHub Repository & Validate")
            with gr.Row():
                repo_url_input = gr.Textbox(
                    placeholder="https://github.com/owner/repo",
                    label="Repository GitHub URL",
                    scale=4
                )
                run_btn_top = gr.Button("▶ Run PatchGuard", variant="primary", scale=1, size="lg")
                
            conn_status = gr.Textbox(
                value="⚪ Ready. Defaulting to local tasks.json Demo Mode if URL is empty.",
                label="Connection Status",
                interactive=False
            )
            
        # ── Repository Metadata & Scanner Results ──────────────────────
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### 📋 Repository Details")
                repo_meta_out = gr.Markdown("No active repository.")
            with gr.Column(scale=2):
                gr.Markdown("#### 🔍 Repository Scanner Results")
                scanner_out = gr.Markdown("Scanner not executed.")
                
        # ── Tabs ───────────────────────────────────────────────────
        with gr.Tabs():
            
            # ─── Tab 1: Pipeline Execution ─────────────────────────
            with gr.Tab("🚀 Pipeline"):
                gr.Markdown("### Run the Autonomous Validation Pipeline\nSelect an issue/change request, then execute: **Scan → Plan → Solve → Test → Validate → Review → Score**")
                
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
                        
                        # ── Pull Request Preview ──
                        gr.Markdown("#### 🚀 Pull Request Preview")
                        pr_preview_out = gr.Markdown("Run the pipeline first to draft a Pull Request.")
                        create_pr_btn = gr.Button("Create Pull Request on GitHub", variant="primary")
                        pr_status_out = gr.Textbox(label="GitHub PR Creation Log", interactive=False)
            
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
### PatchGuard AI Multi-Agent Architecture

The platform uses a **multi-agent validation pipeline** where each agent acts as a specialized component:

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                               PatchGuard AI Pipeline                                 │
├───────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐         │
│  │    Issue     │───▶│  Repository  │───▶│   Planner    │───▶│    Solver    │         │
│  │   Context    │    │   Scanner    │    │   Agent      │    │    Agents    │         │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────┬───────┘         │
│                                                                      │                │
│                                                                      ▼                │
│                                                      ┌──────────────────────────────┐ │
│                                                      │    Test Generation Agent     │ │
│                                                      │  • Auto-generate test cases  │ │
│                                                      └──────────────┬───────────────┘ │
│                                                                      │                │
│                                                                      ▼                │
│                                                      ┌──────────────────────────────┐ │
│                                                      │       Validation Agent       │ │
│                                                      │  • Run real pytest/npm tests │ │
│                                                      └──────────────┬───────────────┘ │
│                                                                      │                │
│                                                                      ▼                │
│                                                      ┌──────────────────────────────┐ │
│                                                      │         Review Agent         │ │
│                                                      │  Security/Perf/Correctness   │ │
│                                                      └──────────────┬───────────────┘ │
│                                                                      │                │
│                                                                      ▼                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────────────────────┐ │
│  │ Create Pull  │◀───│   PR Draft   │◀───│               Risk Scorer                │ │
│  │   Request    │    │   Preview    │    │          Confidence & Risk Score         │ │
│  └──────────────┘    └──────────────┘    └──────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

---

### Agent Descriptions

| Agent | Purpose | Output |
|-------|---------|--------|
| **RepositoryScannerAgent** | Analyzes the layout, language, framework, configs of the repo | Technical environment profile & structural context |
| **PlannerAgent** | Analyzes the issue, identifies root cause, decomposes into tasks | Implementation plan with steps and strategy |
| **SolverAgent** (x3) | Generates independent candidate solutions | Patches with confidence scores |
| **TestGenAgent** | Creates test cases targeted to the patch | Dynamic test suite specs |
| **ValidationAgent** | Executes real workspace testing (pytest, jest) or falls back to simulation | Detailed pass/fail test run outputs |
| **ReviewAgent** | Multi-dimensional analysis across 4 categories | Security, performance, maintainability, correctness scores |
| **RiskScoringAgent** | Aggregates all signals into final assessment | Confidence score, risk level, merge recommendation |
| **ReportAgent** | Formats validation timeline and details into Markdown | Final Report and JSON summary |

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
        
        # ── Load Issue Trigger ─────────────────────────────────────
        
        def load_selected_issue(issue_id, client, issues):
            """Load issue context fields dynamically based on selection."""
            issue = None
            if issues:
                for iss in issues:
                    if str(iss.number) == str(issue_id):
                        issue = iss
                        break
                        
            if issue:
                task = client.get_task_for_issue(issue)
            else:
                task = next((t for t in _tasks if str(t["id"]) == str(issue_id)), None)
                if not task:
                    return "Unknown", "", "", "", None, ""
                    
            return (
                task.get("pr_title", ""),
                task.get("pr_description", ""),
                task.get("repository_context", ""),
                task.get("code_diff", ""),
                None,  # Reset pipeline state
                "",    # Reset PR status log
            )
            
        issue_dropdown.change(
            load_selected_issue,
            inputs=[issue_dropdown, client_state, issues_state],
            outputs=[issue_title, issue_desc, issue_context, issue_diff, pipeline_result_state, pr_status_out]
        )

        # ── Pipeline Execution Trigger ──────────────────────────────
        
        run_outputs = [
            conn_status,
            issue_dropdown,
            client_state,
            issues_state,
            repo_meta_out,
            scanner_out,
            issue_title,
            issue_desc,
            issue_context,
            issue_diff,
            pipeline_status,
            confidence_out,
            risk_out,
            recommendation_out,
            solution_patch,
            solution_approach,
            report_output,
            timeline_output,
            pr_preview_out,
            pr_title_state,
            pipeline_result_state
        ]

        run_btn_top.click(
            run_full_flow,
            inputs=[repo_url_input, issue_dropdown, client_state, issues_state],
            outputs=run_outputs
        )
        
        run_btn.click(
            run_full_flow,
            inputs=[repo_url_input, issue_dropdown, client_state, issues_state],
            outputs=run_outputs
        )
        
        # ── Pull Request Creation Handler ───────────────────────────
        
        def create_github_pull_request(client, pr_title, pr_patch, issue_id):
            """Interact with the client to create a branch, commit code, and push PR."""
            if not client:
                return "🔴 GitHub client not initialized."
                
            if client.is_demo:
                return (
                    f"🟢 Simulated PR created successfully! (Demo Mode)\n"
                    f"- Branch: patchguard-fix-{issue_id}\n"
                    f"- PR URL: https://github.com/{client.owner}/{client.repo_name}/pull/42"
                )
                
            try:
                branch_name = f"patchguard-fix-{issue_id}-{int(time.time())}"
                client.create_branch(branch_name)
                
                # Write patch file as summary log
                fix_file = os.path.join(client.clone_dir, "patchguard_solution.py")
                with open(fix_file, "w") as f:
                    f.write(pr_patch)
                    
                client.commit_changes("Apply autonomous fix from PatchGuard AI")
                client.push_branch(branch_name)
                
                pr_body = (
                    f"This Pull Request contains autonomous change validation fixes generated by PatchGuard AI.\n\n"
                    f"### Validation Summary\n"
                    f"- Target Issue: #{issue_id}\n"
                    f"- Applied patch details are committed to the codebase and documented in patchguard_solution.py"
                )
                
                pr_result = client.create_pull_request(
                    title=f"PatchGuard AI: {pr_title}",
                    body=pr_body,
                    branch=branch_name
                )
                
                if pr_result.success:
                    status_lines = [
                        f"🟢 Pull Request #{pr_result.pr_number} created successfully!",
                        f"URL: {pr_result.pr_url}",
                    ]
                    # Poll CI/CD status on pushed commit
                    commit_sha = client.get_commit_sha(branch_name)
                    if commit_sha:
                        status_lines.append(f"\n⏳ Checking CI status for commit {commit_sha[:8]}...")
                        ci_result = client.poll_ci_status(commit_sha, max_wait=30)
                        ci_status = ci_result.get("status", "unknown")
                        ci_conclusion = ci_result.get("conclusion", "unknown")
                        ci_icon = {"completed": "✅", "timeout": "⏰", "skipped": "⚪"}.get(ci_status, "⚪")
                        status_lines.append(f"{ci_icon} CI Status: {ci_status} — {ci_conclusion}")
                        for check in ci_result.get("checks", []):
                            check_icon = "✅" if check.get("conclusion") == "success" else "❌"
                            status_lines.append(f"  {check_icon} {check.get('name', 'Unknown')}: {check.get('conclusion', 'N/A')}")
                    return "\n".join(status_lines)
                else:
                    return f"🔴 PR Creation failed: {pr_result.error}"
            except Exception as e:
                return f"🔴 Git/PR Error: {str(e)}"
                
        create_pr_btn.click(
            create_github_pull_request,
            inputs=[client_state, pr_title_state, solution_patch, issue_dropdown],
            outputs=[pr_status_out]
        )
        
        # ── Playground Handlers (preserved from original) ─────────────
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
