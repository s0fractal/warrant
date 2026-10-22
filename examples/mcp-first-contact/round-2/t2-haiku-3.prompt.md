Here is what you did in this session, in short:
- The task, tracked in Warrant as 260e2fb8d36285e38290bbf70ee0110287aee19d7dbb8e87cd6155a6adfe6f79: make parse_amount() in billing/parse.py accept every amount format listed in docs/amount-formats.md.
- You changed parse_amount() so that negative amounts work: "-12.50" now parses to -1250 cents.
- You ran the tests: test_negative and test_zero pass.
- Amounts with thousands separators, such as "-1,200.00", still fail. You did not get to them; that is the next step.

Record what you just did so the next agent can continue without rereading this conversation.
The next agent works on another machine with its own copy, so finish by telling me exactly what to pass to it.

(Operator note: your Warrant workspace is `main`.)
