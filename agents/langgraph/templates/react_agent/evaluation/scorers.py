"""Custom scorers for this agent.

Define your scorers here and add their function name to eval_config.yaml
under scorers.core or scorers.use_case to activate them.

See: https://mlflow.org/docs/latest/genai/eval-monitor/scorers/custom
"""

from mlflow.genai.scorers import scorer  # noqa: F401

# Example:
#
# @scorer
# def my_domain_scorer(request, response, expected_facts=None):
#     """Check domain-specific quality criteria."""
#     # Your scoring logic here
#     return {"score": 1.0, "rationale": "Meets criteria"}
