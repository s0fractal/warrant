<!--
Provenance: a review by Codex (OpenAI), passed to this session by the owner on
2026-10-16. It was run on a local checkout at 5c8ed0d, which holds the 1.0.0
text, so its line numbers refer to that version. Kept verbatim below,
followed by a triage against the 1.1.0 text and the code.
-->

Переглянув `warrant/papers` — статтю The Reason Runs Again та супровідні файли на `5c8ed0d338d8`. Висновок: AMEND. Основний внесок сформульований обережно, але аргумент про історичні докази ще перебільшує гарантії.

1. [P1] Timestamp не доводить, яка політика була чинною.
У §5.5 (line 678) OpenTimestamps, archive snapshot і transparency receipt об’єднані під гарантією «historical existence and non-equivocation». Далі сказано, що така композиція закриває мотивуючий сценарій Air Canada.
Контрприклад: оператор може заздалегідь timestamp-нути дві суперечливі політики й потім показувати потрібну. Обидва докази існування будуть справжніми; чинність, повнота історії та відсутність альтернативної версії з цього не випливають. OpenTimestamps гарантує існування даних до певного часу; навіть SCITT §9.1 застерігає від ототожнення порядку реєстрації з порядком випуску.
Потрібно: окремо визначити existence, registration, non-equivocation та authoritative policy activation. Звузити твердження про «закритий сценарій».
2. [P2] «Nothing needs re-anchoring» потребує обмеження.
§4 (line 434) правильно пояснює незмінність WarrantID після перепідписання, але робить надто загальний висновок про anchoring.
Відтворив на demo-record: додав новий криптографічно валідний підпис — envelope змінився, Merkle root залишився тим самим, старий inclusion proof пройшов. Причина: anchor_store (line 116) покриває лише WarrantIDs. Отже, старий anchor не доводить, що доданий підпис існував на момент anchoring.
Потрібно: уточнити, що body anchor зберігається; історичний доказ конкретного набору підписів вимагає commitment до envelope.
3. [P2] Відмінність від найближчих альтернатив названа, але не продемонстрована.
Related work (line 255) прямо відкладає порівняння з OPA. Через це стаття має сильніший доказ інженерної дисципліни, ніж окремої практичної переваги формату.
Потрібно: один наскрізний приклад і таблиця Warrant / OPA + signed bundle / in-toto + transparency: які байти потрібні сторонньому перевіряльнику, що він відтворює, які атаки виявляє та які припущення залишаються.

Сильна частина тексту — явне розмежування replay, semantic binding і authorization, а також чесні межі Lean-доказів та модельних рев’ю.
Перевірки: `tests/anchor.py` пройшов; контрприклад із підписом відтворений. `check_claims.py` на поточному дереві падає на застарілих числах — це очікувано для frozen paper, саме по собі не дефект депозиту. Джерела статті, bibliography та build script збігаються з названим deposit commit. PDF і публічний Zenodo-артефакт повторно не верифіковані; встановлений pandoc не відповідає build pin. Файли не змінював.

---

## Triage (1.1.0 text, 2026-10-16)

| # | Point | Checked | Disposition |
|---|---|---|---|
| P1 | Timestamps do not establish which policy was in force | The 1.1.0 §5.5 still ran existence and non-equivocation together and said the composition "closes" the motivating case. | **TEXT**: §5.5 now separates existence, registration, non-equivocation and authoritative activation. The case is "narrowed, not closed". The introduction's claim is narrowed to match. |
| P2 | "Nothing needs re-anchoring" overreaches | Reproduced independently: an added valid signature leaves the anchor root unchanged, because `anchor_store` commits to WarrantIDs only. The same fact also falsified §8's mitigation for fresh co-signatures. | **TEXT**: §4, §5.5 and §8. An envelope-committing anchor is a possible later tool change, not made here. |
| P3 | The difference from the nearest alternatives is named, not shown | True. | **TEXT**: a comparison table in §2, labelled as drawn from the other systems' documentation. The end-to-end worked case remains undone and is said so. |
