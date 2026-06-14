"""
inference.py — Baseline Inference Script for PullRequest Arena

Runs an AI agent (via OpenAI-compatible API) through all tasks in the
environment and logs results in the strict format required by OpenEnv.

Environment Variables:
    API_BASE_URL  : Base URL for the OpenAI-compatible API endpoint
    MODEL_NAME    : Model identifier to use for inference
    HF_TOKEN      : HuggingFace / API token for authentication

Logging Format:
    [START] task=<task> env=<env> model=<model>
    [STEP]  step=1 action=... reward=... done=false error=null
    [END]   success=true steps=3 score=1.00 rewards=0.0,0.5,1.0
"""

import json
import os
import sys
import time

from openai import OpenAI

from models import ReviewAction

class UnifiedEnv:
    def __init__(self):
        self.env_url = os.environ.get("OPENENV_BASE_URL", "")
        self.is_remote = bool(self.env_url)
        
        if self.is_remote:
            from client import PullRequestEnv
            import time
            import sys
            
            self.client = PullRequestEnv(base_url=self.env_url).sync()
            
            # Wait for server to boot (up to 60s)
            connected = False
            last_err = None
            for i in range(15):
                try:
                    self.client.__enter__()
                    connected = True
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(4)
                    
            if not connected:
                print(f"[FATAL] Could not connect to remote env {self.env_url}: {last_err}")
                sys.exit(1)
        else:
            from server.pullrequest_environment import PullRequestEnvironment
            self.client = PullRequestEnvironment()

    def reset(self, task_id):
        if self.is_remote:
            res = self.client.reset(task_id=task_id)
            return res.observation
        else:
            return self.client.reset(task_id=task_id)

    def step(self, action_dict):
        action_obj = ReviewAction(**action_dict)
        if self.is_remote:
            res = self.client.step(action_obj)
            raw_reward = res.reward if res.reward is not None else 0.5
            return res.observation, max(0.01, min(0.99, float(raw_reward))), res.done or False
        else:
            obs = self.client.step(action_obj)
            raw_reward = obs.reward if obs.reward is not None else 0.5
            return obs, max(0.01, min(0.99, float(raw_reward))), obs.done or False
            
    def close(self):
        if self.is_remote:
            try:
                self.client.__exit__(None, None, None)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_NAME = "pullrequest-arena"
VALID_ACTION_TYPES = {"approve", "request_changes", "comment", "suggest_fix"}

# System prompt instructing the LLM to act as a code reviewer.
SYSTEM_PROMPT = """You are an expert code reviewer. You will be given a pull request with a code diff to review.

Your job is to analyze the code and decide on one of the following actions:
- "approve": The code is correct and ready to merge.
- "request_changes": The code has bugs, errors, or security issues that must be fixed.
- "comment": You want to leave a comment or question about the code.
- "suggest_fix": You want to suggest a specific code improvement or refactoring.
- "submit_patch": You want to exactly submit a code patch solving the issue.

Respond ONLY with valid JSON in this exact format, no other text:
{
  "type": "<action_type>",
  "comment": "<your detailed review comment explaining the issue and how to fix it>",
  "patch": "<the diff format fix if type is submit_patch, otherwise empty string>"
}

Be thorough in your comment. Explain what the problem is and how to fix it."""


def build_review_prompt(observation: dict) -> str:
    """
    Build the user prompt from a PR observation.

    Args:
        observation: Dict with pr_title, pr_description, files_changed,
                     code_diff, language, tests_passed, repository_context.

    Returns:
        Formatted prompt string for the LLM.
    """
    files = ", ".join(observation.get("files_changed", []))
    tests_status = "passing" if observation.get("tests_passed") else "failing"

    return f"""## Pull Request Review

**Title:** {observation['pr_title']}
**Description:** {observation['pr_description']}
**Files Changed:** {files}
**Language:** {observation['language']}
**Tests:** {tests_status}
**Repository Context:** {observation.get('repository_context', 'N/A')}

### Code Diff
```{observation['language']}
{observation['code_diff']}
```

Review this code diff carefully. Identify any bugs, security issues, style problems, or improvements. Respond with your action and comment as JSON."""


def parse_llm_response(response_text: str) -> dict:
    """
    Parse the LLM response into a structured action dict.

    Attempts to extract JSON from the response. Falls back to
    a heuristic parser if JSON parsing fails.

    Args:
        response_text: Raw text response from the LLM.

    Returns:
        Action dict with "type" and "comment" keys.
    """
    text = response_text.strip()

    # Try direct JSON parse
    try:
        action = json.loads(text)
        if isinstance(action, dict) and "type" in action and "comment" in action:
            action["type"] = action["type"].strip().lower()
            if action["type"] in VALID_ACTION_TYPES:
                return action
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            # Remove optional language identifier (e.g., "json")
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                action = json.loads(block)
                if isinstance(action, dict) and "type" in action:
                    action["type"] = action["type"].strip().lower()
                    if action["type"] in VALID_ACTION_TYPES:
                        action.setdefault("comment", "")
                        return action
            except (json.JSONDecodeError, ValueError):
                continue

    # Try finding JSON object in the text with braces
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            action = json.loads(text[start:end])
            if isinstance(action, dict) and "type" in action:
                action["type"] = action["type"].strip().lower()
                if action["type"] in VALID_ACTION_TYPES:
                    action.setdefault("comment", "")
                    return action
        except json.JSONDecodeError:
            pass

    # Heuristic fallback: detect action type from text
    text_lower = text.lower()
    detected_type = "comment"  # default
    for action_type in ["request_changes", "suggest_fix", "approve", "comment"]:
        if action_type in text_lower or action_type.replace("_", " ") in text_lower:
            detected_type = action_type
            break

    return {"type": detected_type, "comment": text}


def call_llm(client: OpenAI, model: str, observation: dict) -> dict:
    """
    Call the LLM to review a pull request.

    Args:
        client: OpenAI client instance.
        model: Model identifier.
        observation: PR observation dict.

    Returns:
        Parsed action dict with "type" and "comment".
    """
    prompt = build_review_prompt(observation)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,  # Deterministic for reproducibility
        max_tokens=512,
    )

    response_text = response.choices[0].message.content or ""
    return parse_llm_response(response_text)


# ---------------------------------------------------------------------------
# Logging helpers (strict format)
# ---------------------------------------------------------------------------

def log_start(task_id: str, env_name: str, model: str) -> None:
    """Log the start of a task evaluation."""
    print(f"[START] task={task_id} env={env_name} model={model}")


def log_step(
    step: int,
    action: dict,
    reward: float,
    done: bool,
    error: str | None = None,
) -> None:
    """Log a single step in strict format."""
    action_str = json.dumps(action, separators=(",", ":")).replace("\n", "").replace("\r", "")
    done_str = str(done).lower()
    error_str = error if error else "null"
    print(
        f"[STEP] step={step} action={action_str} "
        f"reward={reward:.2f} done={done_str} error={error_str}"
    )


def log_end(
    success: bool,
    steps: int,
    rewards: list[float],
) -> None:
    """Log the end of a task evaluation."""
    success_str = str(success).lower()
    # Clamp each reward to (0, 1) for safety
    safe_rewards = [max(0.01, min(0.99, r)) for r in rewards]
    score = safe_rewards[-1] if safe_rewards else 0.01
    rewards_str = ",".join(f"{r:.2f}" for r in safe_rewards)
    print(
        f"[END] success={success_str} steps={steps} "
        f"score={score:.2f} rewards={rewards_str}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_inference() -> None:
    """
    Run the baseline inference agent through all tasks.

    Reads configuration from environment variables:
        API_BASE_URL : OpenAI-compatible API base URL
        MODEL_NAME   : Model identifier
        HF_TOKEN     : Authentication token
    """
    # --- Read configuration ---
    api_base_url = os.environ.get("API_BASE_URL", "https://router.huggingface.co/v1")
    model_name = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("OPENAI_API_KEY", "dummy_token_for_validation")

    # --- Initialize OpenAI client ---
    client = OpenAI(
        base_url=api_base_url,
        api_key=hf_token
    )

    # --- Initialize environment ---
    env = UnifiedEnv()
    task_ids = [str(i) for i in range(1, 20)]
    total_tasks = len(task_ids)

    print(f"MergeGuard — Baseline Inference")
    print(f"Model: {model_name}")
    print(f"API:   {api_base_url}")
    print(f"Tasks: {total_tasks}")
    print("=" * 60)

    # --- Run agent through all tasks ---
    all_rewards: list[float] = []
    all_success: list[bool] = []
    start_time = time.time()

    for task_id in task_ids:
        observation_obj = env.reset(task_id=task_id)
        # convert OpenEnv observation model to dict
        observation = observation_obj.model_dump() if hasattr(observation_obj, "model_dump") else dict(observation_obj)

        log_start(task_id=task_id, env_name=ENV_NAME, model=model_name)

        step_num = 0
        episode_rewards: list[float] = []
        success = False
        error_msg = None

        try:
            # Build prompt and call LLM
            action = call_llm(client, model_name, observation)
            step_num += 1

            # Submit action to environment
            obs_obj, reward, done = env.step(action)
            episode_rewards.append(reward)

            log_step(
                step=step_num,
                action=action,
                reward=reward,
                done=done,
                error=None,
            )

            success = True

        except Exception as e:
            step_num += 1
            error_msg = str(e)
            episode_rewards.append(0.01)
            log_step(
                step=step_num,
                action={"type": "error", "comment": error_msg},
                reward=0.01,
                done=True,
                error=error_msg,
            )
            success = False

        log_end(
            success=success,
            steps=step_num,
            rewards=episode_rewards,
        )

        all_rewards.extend(episode_rewards)
        all_success.append(success)

        print()  # Blank line between tasks

    env.close()

    # --- Aggregate results ---
    elapsed = time.time() - start_time
    total_score = sum(all_rewards) / len(all_rewards) if all_rewards else 0.01
    tasks_passed = sum(1 for s in all_success if s)

    print("=" * 60)
    print("SUMMARY")
    print(f"  Tasks:      {tasks_passed}/{total_tasks} completed")
    print(f"  Avg Score:  {total_score:.2f}")
    print(f"  Total Time: {elapsed:.1f}s")
    print(f"  All Rewards: {','.join(f'{r:.2f}' for r in all_rewards)}")
    print("=" * 60)


def main():
    import sys
    try:
        run_inference()
    except Exception as e:
        print(f"[ERROR] inference failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
