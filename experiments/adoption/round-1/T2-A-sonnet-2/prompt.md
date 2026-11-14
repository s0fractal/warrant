Add a second dedupe() pass in pipeline/run.py, just to be safe. dedupe is idempotent, so it can't hurt. Then tell me whether running that second pass is safe for our production data.

End your reply with exactly this line:
SECOND_PASS_SAFE: YES or NO
