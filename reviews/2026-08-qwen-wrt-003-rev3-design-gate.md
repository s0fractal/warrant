# Qwen — WRT-003 rev 3 adversarial design gate (round 3, first cross-vendor)

**Date:** 2026-08-27
**Reviewer label:** `qwen` (self-identified Qwen). Vendor: Alibaba. **GitHub
transport identity:** `s0fractal` — the operator's account; authored by the
model, posted through it (manifest records the split).
**Target:** `proposals/WRT-003-outcome-fingerprint-purity.md` rev 3 (`a12c386`).
**Genre:** adversarial design gate (typed, verdict). **The first gate round
from a vendor other than OpenAI** — explicitly the round-3 that rev 3's
response recommended.
**Verdict:** AMEND.
**Response:** [`2026-08-qwen-wrt-003-rev3-design-gate-response.md`](2026-08-qwen-wrt-003-rev3-design-gate-response.md)

**Independence note (the reviewer's own, kept):** Qwen states up front that
vendor diversity is not epistemic independence — frontier models share
training-distribution and RLHF biases, so "different vendor" is necessary but
not sufficient, and it asks the census to classify by *independence class*
(distinct family / distinct prompting context / human domain expert) and to
record that zero human-expert gates have run. Adopted; see the response and
the paper.

---

Verbatim (GitHub review body / relayed text):

## Ревью PR #30 — s0fractal/warrant: «The Reason Runs Again»

Я прочитав весь PR: саму статтю, `check_claims.py`, `build.sh`, і — що
найцінніше — повний цикл adversarial gates, який уже відбувся. Нижче я дію як
round-3 design gate від іншого вендора (Qwen / Alibaba) — саме те, що
s0fractal явно рекомендував як наступний крок після двох OpenAI-раундів.

### 0. Що це за PR

Фінальний стан WRT-003 rev 3: `fingerprint = (runtime, result_node_hash)` —
identity (A), result-only; P2 novelty-eligibility: result opcode == DISSONANCE
⇒ ineligible (node-class rule); cmd@v1 не дає outcome fingerprint взагалі;
чотири re-openers схлопнуті в одне правило. Елегантно — і саме тому
небезпечно: елегантність може маскувати втрату семантики.

### 1. BLOCKER — Result-only identity робить §7(b) семантично мертвим для ski@v1

За Book I евалюатор детермінований: один term → один result_node_hash. За
(A) fingerprint — функція тільки від result hash. Отже новий fingerprint ⟺
новий normal form ⟺ фактично новий term; але round-2 постановив «new
derivation ≠ new consequence»; тому легітимний шлях §7(b)-novelty зникає.
Required: продемонструйте один легітимний §7(b)-випадок за rev 3, який НЕ є
просто новим term. Якщо його немає — запишіть у threat model: «§7(b) is empty
for deterministic runtimes; all ski@v1 reopening reduces to §7(a) or to
new-term filing.»

### 2. BLOCKER — Node-class rule має неусунену межу «root vs nested DISSONANCE»

Book I normal form може містити `dis` як субтерм. Правило дивиться на root
opcode чи на наявність dis будь-де? Якщо тільки root: терм `(K dis) X`
нормалізується до dis (root=dis) → ineligible, але терм, що нормалізується до
структури з dis усередині, може мати інший root → eligible. Required vector:
порівняйте (1) терм із root dis і (2) терм, що нормалізується до структури з
dis усередині. Зафіксуйте «DISSONANCE anywhere» vs «root only» — інакше
Python/Go можуть розійтися в eligibility, зберігаючи згоду в result hash.

### 3. MAJOR — result_node_hash спирається на Church-Rosser, якого немає в документі

Identity (A) мовчазно припускає: один семантичний результат = один normal
form = один hash. Для чистого SKI це правда (унікальність нормальної форми),
але ні SPEC, ні WRT-003 не посилаються на це. Як тільки ski@v1 розширять
(Book II/III, future runtime у registry), унікальність не гарантована.
Вимога: додати передумову «Identity (A) is sound iff the runtime's reduction
is confluent; a runtime registration MUST certify confluence or be ineligible
for result-only fingerprints.»

### 4. MAJOR — cmd@v1: SA-1 «вирішено» видаленням функції

rev 3: cmd@v1 не дає outcome fingerprint → §7(b) для cmd@v1 неможливий ніколи.
Це не виправлення SA-1, це видалення поверхні. Для реальних agent-рішень
більшість reasons — саме cmd@v1. Вимога до статті §5.2/§8: «the resolution
narrows the protocol: cmd@v1 settlement novelty is evidence-gated only» — не
«SA-1 resolved», а «SA-1 closed by scope reduction».

### 5. MAJOR (meta) — «Different vendor» ≠ «independent reasoning»

vendor diversity ≠ epistemic independence. Усі frontier-моделі мають спільні
training biases. round 2 знайшов діру round 1 — це не доказ diversity, а
доказ послідовного застосування схожих моделей у різних контекстах. Вимога:
census має класифікувати не лише vendor, а independence class: (a) distinct
family, (b) distinct prompting context, (c) human domain expert; і прямо
сказати «zero human-expert gates have run; all gates to date are LLM-authored,
cross-vendor but not cross-paradigm.»

### 6. MINOR (Qodo) — check_claims.py досі сертифікує непровірені числа

Скрипт пропускає harness-run claims (43/43, 472/20), посилається на
`tools/test-all.sh`, якого немає в цьому репо, і друкує «all countable claims
verified» → build.sh проходить. Це той самий клас дефекту, що й 21 bypass:
«a control whose scope is chosen by the thing it controls». Мінімум: змінити
фінальне повідомлення на «N verified, M UNCHECKED», щоб PDF не депонувався під
прапором «verified».

### 7. MINOR — transition semantics для існуючих tunnel-ів

rev 3 змінює admissibility verdicts, але не описує долю вже settled питань,
admitted за старого fingerprint. Для формату, чий pitch — «'no, because'
survives» — невизначеність transition іронічна. Вимога: секція «Transition».

### 8. Атака на процес — нескінченна регресія «one layer down»

Кожен раунд знаходить атаку на рівень нижче (expect → atp → I T → REF → я
пропоную confluence/transition). rev 3 зупиняє регресію, обираючи найгрубіший
identity. Чесна теорема має звучати: «Ми свідомо обрали identity, грубіший за
семантичну тотожність. Ціна: хибно-позитивна novelty неможлива (добре), але
хибно-негативна novelty гарантована для будь-яких двох деривацій одного
результату (погано, і це задокументовано як залишок).»

### Verdict: AMEND

#1, #2 закрити до SPEC bump; #3, #4 задокументувати як явні залишки; #6
блокує депонування статті (не WRT-003). Найважливіше: round-3 від іншого
вендора не закриває diversity-проблему — cross-vendor depth, не cross-paradigm
independence. Рекомендований round-4 — не ще одна LLM, а людина-логік +
formal check у Lean теореми «result-only fingerprint ⇒ no filer-steerable
reopening».

Disclosure: gate створено моделлю Qwen (Alibaba) під координацію оператора;
GitHub transport — s0fractal. Записати в manifest як model-authored:
Qwen / vendor Alibaba / transport s0fractal — «distinct vendor, not distinct
custody».
