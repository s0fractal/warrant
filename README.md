# The merge gate's receipts

Written by the job `receipt` of `.github/workflows/merge-on-acceptance.yml` (`warrant/receipt.py`): one record for each merge the gate made.
Each record says that GitHub reports this pull request merged as this commit from this head, signed by the key of `merge-gate`. No rule of any store counts it.
