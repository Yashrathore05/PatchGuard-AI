import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

RESULTS_DIR = "results"
RESULTS_FILE = os.path.join(RESULTS_DIR, "benchmark_results.json")

def parse_inference_output(output: str):
    """Parses OpenEnv strict logs from inference.py"""
    metrics = {
        "tasks": 0,
        "successes": 0,
        "bug_detections": 0,
        "patch_attempts": 0,
        "patch_successes": 0,
        "total_rewards": []
    }
    
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
            
        if line.startswith("[STEP]"):
            # Example: [STEP] step=1 action={"type":"submit_patch","comment":"..."} reward=0.85 done=true error=null
            try:
                # Find reward
                reward_start = line.find("reward=") + 7
                reward_end = line.find(" ", reward_start)
                reward_val = float(line[reward_start:reward_end])
                metrics["total_rewards"].append(reward_val)
                
                # Check patch / bug tracking from action string
                action_start = line.find("action=") + 7
                action_end = line.find(" reward=")
                action_str = line[action_start:action_end]
                
                if "request_changes" in action_str or "submit_patch" in action_str:
                    metrics["bug_detections"] += 1
                
                if "submit_patch" in action_str:
                    metrics["patch_attempts"] += 1
                    if reward_val >= 0.85:
                        metrics["patch_successes"] += 1
                        
            except ValueError:
                pass
                
        elif line.startswith("[END]"):
            metrics["tasks"] += 1
            if "success=true" in line:
                metrics["successes"] += 1

    return metrics

def run_benchmark(model_name: str):
    print(f"MergeGuard — Baseline Inference for model: {model_name}...")
    
    env = os.environ.copy()
    env["MODEL_NAME"] = model_name
    
    result = subprocess.run([sys.executable, "inference.py"], env=env, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("[ERROR] Inference failed:")
        print(result.stderr)
        return None
        
    metrics = parse_inference_output(result.stdout)
    
    # Calculate final scaled rates
    tasks = max(1, metrics["tasks"])
    avg_reward = sum(metrics["total_rewards"]) / len(metrics["total_rewards"]) if metrics["total_rewards"] else 0.0
    
    # Clamp helper: validator rejects exactly 0.0 and 1.0
    def _clamp(v): return round(max(0.01, min(0.99, v)), 2)

    return {
        "model": model_name,
        "timestamp": datetime.now().isoformat(),
        "average_reward": _clamp(avg_reward),
        "bug_detection_rate": _clamp(metrics["bug_detections"] / tasks),
        "patch_success_rate": _clamp(metrics["patch_successes"] / max(1, metrics["patch_attempts"])),
        "task_completion_rate": _clamp(metrics["successes"] / tasks)
    }

def print_leaderboard(results):
    print("\n" + "=" * 50)
    print("🏆 MERGEGUARD LEADERBOARD")
    print("=" * 50)
    print(f"{'Model':<25} | {'Avg Score':<10} | {'Completion':<10}")
    print("-" * 50)
    
    # Sort by descending score
    sorted_results = sorted(results, key=lambda x: x["average_reward"], reverse=True)
    for res in sorted_results:
        print(f"{res['model']:<25} | {res['average_reward']:<10} | {res['task_completion_rate']:<10}")
    print("=" * 50 + "\n")

def main():
    parser = argparse.ArgumentParser(description="MergeGuard Benchmark Utility")
    parser.add_argument("--model", type=str, required=True, help="HuggingFace / OpenAI Model Identifier")
    args = parser.parse_args()

    # Verify OpenEnv token presence natively avoiding crashes
    if "HF_TOKEN" not in os.environ and "OPENAI_API_KEY" not in os.environ:
        print("[WARNING] HF_TOKEN or OPENAI_API_KEY environment variable is not set. Inference may fail if the API requires auth.")

    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    # Run inference and compile metrics
    stats = run_benchmark(args.model)
    if stats is None:
        sys.exit(1)

    # Load existing records
    history = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                pass
                
    # Update matched model or append natively
    existing = next((i for i, x in enumerate(history) if x["model"] == stats["model"]), None)
    if existing is not None:
        history[existing] = stats
    else:
        history.append(stats)

    with open(RESULTS_FILE, "w") as f:
        json.dump(history, f, indent=4)

    print_leaderboard(history)

if __name__ == "__main__":
    main()
