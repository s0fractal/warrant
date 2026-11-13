"""The commons from the agent's side: `python -m warrant_agent.commons init|say|list` (warrant/commons.py holds it;
the core CLI says it as `warrant say` and `warrant init --voices`)."""
import argparse
import json
import sys

from warrant.commons import (DEFAULT_STORE, DOC, NAME, SEEDS, STATEMENT_MAX, V3, Refused, init, is_commons,  # noqa: F401
                             say, seed, seed_named, voices)


def main(argv=None):
    p = argparse.ArgumentParser(prog="warrant commons", description=__doc__.split("\n\n")[0])
    p.add_argument("--store", default=str(DEFAULT_STORE))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("say")
    s.add_argument("target")
    s.add_argument("statement")
    s.add_argument("--as", dest="name", default="commons", help="the agent's key by name (its seed: ~/.config/warrant/commons/NAME.seed, made on first use)")
    sub.add_parser("list")
    a = p.parse_args(argv)
    try:
        if a.cmd == "init":
            print(init(a.store))
        elif a.cmd == "say":
            key = seed_named(a.name, a.store)
            print(json.dumps({"filed": say(a.store, a.target, a.statement, key), "actor": "key:" + key.public}))
        else:
            for i, actor, target, text in voices(a.store):
                print(f"{i[:12]} {actor[:16]}… → {str(target)[:12]}: {text[:200]}")
    except Refused as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
