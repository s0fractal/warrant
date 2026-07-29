import harness
from model import World, Rec, Model
P_gen=(frozenset({"Q"}),1); P_lose=(frozenset({"Q","Z"}),2); P_win=(frozenset({"A"}),1)
w=World(pinned_roots={"J":{"g"}},pinned_policy={"J":P_gen},
        pinned_keys={a:set(k) for a,k in {"Q":{"kQ"},"A":{"kA"},"Z":{"kZ"},"Admin":{"kAdmin"}}.items()})
for r in [Rec("g",frozenset(),"Admin","ordinary",jur="J",filing=("Admin","kAdmin")),
 Rec("succ_lose",frozenset({"g"}),"Q","policy-succession",jur="J",new_policy=P_lose,threshold=frozenset({("Q","kQ")})),
 Rec("succ_win",frozenset({"g"}),"Q","policy-succession",jur="J",new_policy=P_win,threshold=frozenset({("Q","kQ")})),
 Rec("res",frozenset({"succ_lose","succ_win"}),"Q","policy-resolution",jur="J",
     resolves=frozenset({"succ_lose","succ_win"}),new_policy=P_win,threshold=frozenset({("Q","kQ")})),
 Rec("adopt_X",frozenset({"succ_lose"}),"Q","root-adoption",jur="J",subject="X",
     threshold=frozenset({("Q","kQ"),("Z","kZ")}))]:
    w.add(r)
m=Model(w,frozenset(w.recs),"J")
assert not m.in_lineage("succ_lose"), "premise: the branch must actually lose"
harness.violation(expected="X not admitted (its authorising quorum lost)",
                  got=("X admitted" if "X" in m.admits() else "X not admitted"),
                  note="quorum existing only under the losing policy adopts a root that reaches admits()")
