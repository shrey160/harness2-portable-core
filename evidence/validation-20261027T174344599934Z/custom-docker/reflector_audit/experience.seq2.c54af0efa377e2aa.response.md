<edits>
component: scripts/normalize.py
change: removed the positive-only amount filter
observed: both signed records were preserved in the probe output
verdict: helped
</edits>
<experience>
cue: A JSON amount list can contain credits and debits
lesson: Sum every signed Decimal when producing the total.
evidence: The selected probe retained the negative records and its total matched the independent task calculation.
confidence: high
</experience>