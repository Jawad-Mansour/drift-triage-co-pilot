COMMS_PROMPT = """\
You are an ML operations assistant writing a status update for the drift monitoring dashboard.

Investigation details:
- Feature:           {feature_name}
- PSI score:         {psi_score}
- Severity:          {severity}
- Triage rationale:  {triage_rationale}
- Proposed action:   {proposed_action}
- Action rationale:  {action_rationale}
- Status:            {status}
- Operator note:     {operator_note}

Write a concise 2-3 sentence human-readable status update.
Be specific about numbers. Do not use markdown. Do not repeat the label names.
"""
