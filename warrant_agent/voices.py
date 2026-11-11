"""Who a voice is: the keys behind a name, not the name (R04 of the observer pack, in part).

An actor's name means what the trust of the store holding the record binds it to: `claude` in one store and `claude`
in another are one source only if a key is bound to both, and two names bound to one key are one source however many
stores repeat it. A `key:<hex>` name (the commons) is its key. A name its store binds to no key, or a record
its store admitted unsigned, is known by (name, store) alone and is no one's voice. `groups` joins voices that share a key; the floor counts groups, and names the joins and splits
a reader would otherwise miss.
What it does not establish: that two keys are two people (one hand can hold many keys), or anything about a source
that fed several stores without signing in them (shared upstream remains unmodelled)."""


def keys_of(trust, actor):
    """The keys `trust` binds to `actor` (a `key:<hex>` name is its own key); empty when unknown."""
    if actor.startswith("key:"):
        return {actor[4:]}
    if not isinstance(trust, dict):
        return set()
    ks = trust.get("keys", {}).get(actor, [])
    return set(ks) if isinstance(ks, list) else set()


def groups(voices):
    """[{"names", "stores", "keys", "members"}] of `voices` [(name, store, keys)] joined where they share a key, in a
    stable order; `members` are the indices of the voices joined.
    A voice with no key is a group of its own unless another voice has its very (name, store)."""
    parent = list(range(len(voices)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, (name, store, keys) in enumerate(voices):
        for k in sorted(keys) or [("unbound", name, store)]:
            if k in seen:
                parent[find(i)] = find(seen[k])
            else:
                seen[k] = i
    out = {}
    for i, (name, store, keys) in enumerate(voices):
        g = out.setdefault(find(i), {"names": set(), "stores": set(), "keys": set(), "members": set()})
        g["members"].add(i)
        g["names"].add(name)
        g["stores"].add(store)
        g["keys"] |= keys
    return sorted(({k: sorted(v) for k, v in g.items()} for g in out.values()), key=lambda g: (g["names"], g["stores"]))


def notes(gs):
    """[sentence] a reader needs where names mislead: one source under several names, one name for several sources."""
    out = [" = ".join(g["names"]) + ": один ключ" for g in gs if len(g["names"]) > 1]
    by_name = {}
    for g in gs:
        for n in g["names"]:
            by_name.setdefault(n, []).append(g)
    out += [f"{n}: {len(v)} різні джерела (" + ", ".join("/".join(g["stores"]) for g in v) + ")"
            for n, v in sorted(by_name.items()) if len(v) > 1]
    out += [", ".join(g["names"]) + " (у " + ", ".join(g["stores"]) + "): без ключа, яким сховище знає це ім'я"
            for g in gs if not g["keys"]]
    return out
