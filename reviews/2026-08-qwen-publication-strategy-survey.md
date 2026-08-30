# Qwen — publication-potential survey (untyped, not a gate)

**Date:** 2026-08-27
**Reviewer label:** `qwen` (surface not recorded by the operator). Vendor: Alibaba.
**Genre:** scouting survey — an assessment of what papers this repository
could yield and where they could be sent. **No severities, no verdict, not an
adversarial gate**; filed in the ledger because it reviews the project's
publishability, which is a property of the project.
**Target:** the repository at large; delivered while PR #30 (the flagship
paper draft) was in its first review round, apparently without having read it.
**Provenance:** relayed verbatim by the operator.
**Response (joint, with the Gemini survey):**
[`2026-08-publication-strategy-surveys-response.md`](2026-08-publication-strategy-surveys-response.md)

---

The survey as received (verbatim; the response file notes the factual
corrections — including an invented expansion of "ATP" — rather than editing
them away here):

## Загальна характеристика проекту

**Warrant** — це криптографічний протокол для створення **незмінних,
верифікованих записів рішень** AI агентів. Ключова ідея: коли агент приймає
рішення (accept/reject/propose), він створює підписаний JSON-запис, який
містить: **що** було вирішено; **згідно з якою політикою** (піниться хешем);
**чому** (причини можуть бути виконуваними перевірками); **на основі яких
доказів**; **хто** прийняв рішення.

## Наукова новизна та унікальність

1. **Re-executable Reasons** — найбільш інноваційний аспект. На відміну від
   традиційних audit logs, де причини — це текст, Warrant дозволяє причинам
   бути **виконуваними програмами** (`ski@v1` runtime): верифікатор може
   **перевиконати** логіку рішення; детермінізм гарантується через SKI
   combinator calculus; memory та work bounded через ATP (Algorithmic Turing
   Pricing).
2. **Content-Addressed Policy Binding** — політики пінюються **хешем їхніх
   байтів**, а не іменем. Запобігає policy drift, retroactive justification,
   scope manipulation.
3. **Adversarial Security Model** — надзвичайно детальна модель загроз (10+
   Security Assumptions, 6+ Non-Goals), включаючи self-approving changes,
   courtroom attacks, multi-party collusion.
4. **Multi-Implementation Verification** — три незалежні імплементації
   (Python, Go, Rust) зі 138 conformance vectors, differential testing.
5. **AI Agent Governance** — один з перших проектів, який серйозно ставиться
   до управління AI агентами через криптографічні механізми.

## Запропоновані статті (6)

| # | Стаття | Venue | Оцінка | Ймовірність прийняття (за рев'юером) |
|---|---|---|---|---|
| 1 | *Warrant: Cryptographically Verifiable Decision Records for Autonomous AI Agents* — system paper | USENIX Security / IEEE S&P / ACM CCS / NDSS | 5/5 | 30–40% |
| 2 | *Executable Reasons: Bridging the Gap Between Prose Justifications and Verifiable Computation* — WPL дизайн, компіляція в SKI terms, ATP budgeting | POPL / ICFP / PLDI / OOPSLA | 4/5 | 25–35% |
| 3 | *Adversarial Robustness in AI Governance: Lessons from Breaking Warrant's Self-Verification Mechanisms* — 21 bypass, courtroom attacks, "control whose scope is chosen by the thing it controls" | USENIX / CCS applied / WOOT / DEF CON | 4/5 | 50–60% |
| 4 | *Multi-Party AI Agent Governance* — settlement, threshold signatures, prior DAG, порівняння з DAO governance | AFT / WTSC / ICDCS / PODC | 3/5 | 40–50% |
| 5 | *Content-Addressed Policy Binding: Preventing Policy Drift* — short/workshop | HotOS / HotSec / SysML | 3/5 | 60–70% |
| 6 | *Σ-GLYPH + Warrant: A Verified Stack for Safe AI Agent Execution* — end-to-end integration | OSDI / SOSP / EuroSys / ASPLOS | 5/5 | 20–30% |

## Рекомендована стратегія (фази)

- **Фаза 1 (3–6 міс., quick wins):** Paper 3 (adversarial analysis — найлегше
  написати, високий impact), Paper 5 (workshop short).
- **Фаза 2 (6–12 міс., core):** Paper 1 (system paper, top security venue),
  Paper 2 (PL venue).
- **Фаза 3 (12–18 міс., ambitious):** Paper 6 (verified stack, top systems),
  Paper 4 (distributed).

## Критичні фактори успіху (за рев'юером)

Додати: formal verification (Lean/Coq для security properties, formal
semantics для WPL, model checking); performance evaluation (benchmarks,
порівняння з in-toto/SLSA, scalability 1000+ agents / 1M+ decisions);
real-world case studies (інтеграції, production data, user studies); security
analysis (STRIDE/PASTA, pentesting); детальніший related work (in-toto, SLSA,
W3C PROV, RO-Crate, DAO governance).

## Ризики (за рев'юером)

Технічні: performance overhead, complexity, lack of formal verification.
Академічні: "це просто audit logs з crypto" (novelty objection), слабка
evaluation, related-work overlap. Практичні: limited adoption,
reproducibility, «проект може зупинитись до завершення papers».

## Висновок (за рев'юером)

Найсильніше: executable reasons, adversarial security model,
multi-implementation verification, актуальність AI governance. Найслабше:
відсутність formal verification, обмежена performance evaluation, немає
real-world case studies, треба краще артикулювати novelty vs. audit logs.
Загальна оцінка: 4/5 — «strong publication potential with proper execution».
Стартувати з Paper 3, паралельно Paper 1.
