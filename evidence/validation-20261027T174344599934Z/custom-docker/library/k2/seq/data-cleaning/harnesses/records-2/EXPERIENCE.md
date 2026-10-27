# records-2

- adopted: `c2`  (run `custom_json_records-oc-seq2/records-2/c2`)
- components: 1 scripts; 55 always-on chars

## Why this was chosen
The normalized signed total matches the source records.

## What each edit did
component: scripts/normalize.py
change: removed the positive-only amount filter
observed: both signed records were preserved in the probe output
verdict: helped

## Transferable lesson
- **cue**: A JSON amount list can contain credits and debits
- **lesson**: Sum every signed Decimal when producing the total.
- **evidence**: The selected probe retained the negative records and its total matched the independent task calculation.
- **confidence**: high
