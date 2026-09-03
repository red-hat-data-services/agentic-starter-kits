"""Custom scorers for this agent.

Define your scorers here and add their function name to eval_config.yaml
under scorers.core or scorers.use_case to activate them.

See: https://mlflow.org/docs/latest/genai/eval-monitor/scorers/custom
"""

from mlflow.genai.scorers import scorer  # noqa: F401

# Example:
#
# from mlflow.entities import Feedback
#
# @scorer
# def my_domain_scorer(*, inputs, outputs, expectations=None, trace=None):
#     """Check domain-specific quality criteria."""
#     # Your scoring logic here
#     return Feedback(value=1.0, rationale="Meets criteria")
