# Earnings-Call Transcript Extraction

Use for U.S./Hong Kong earnings calls, results webcasts and relevant briefing transcripts. The same attribution rules apply to an A-share results briefing or investor-relations activity record, but a written activity summary is not automatically a verbatim call transcript. Extract the requested scope; research interpretation and four-cycle comparison apply only when requested or relevant to the active research task.

## Identity, Retrieval And Coverage

Resolve issuer, fiscal period, meeting date/time/timezone, event type, source language, host and actual source URL. Distinguish fiscal period from meeting date and transcript publication/revision date; apply the research cutoff to information actually available then. A later written transcript does not prove the original public audio was unavailable earlier, but a historical reconstruction must identify which source was then accessible.

Prefer the issuer's IR recording and official transcript/prepared remarks. An exchange filing, 8-K/6-K exhibit, results presentation or press release may contain only prepared material, not the call. If no official transcript exists, use an accessible third-party transcript with publisher and revision status; if audio/video is the only usable source, use the available `watch` workflow for timestamped transcription. Read that skill before executing its media workflow. Do not assume a vendor/API is installed, purchase access or bypass restrictions. If original audio cannot be obtained, preserve the transcript's provenance and unresolved discrepancies rather than claim it was audio-verified.

Record coverage separately for prepared remarks, Q&A, follow-ups, audio gaps and slides/visuals. Compare opening/closing and section boundaries or recording duration where available before claiming completeness; a single excerpt or a recap is not the whole event. Audio may not capture tables referred to as “on this slide”; inspect available slides when the table carries the claim, otherwise mark the visual detail missing. Distinguish “event not found,” “recording inaccessible,” “Q&A absent from this source,” and “confirmed no Q&A.” Do not assume all issuers hold quarterly calls, or that all public sessions cover the same audience or language.

## Preserve The Exchange Before Compressing It

Maintain speaker identity/role and a timestamp or source section/paragraph locator. Keep a material question, answer, follow-up and correction together. Identify analyst premises separately from management's actual response; neither silence, a partial answer nor repetition confirms the premise. If speaker identity or a name is uncertain, mark it rather than guessing. An operator or simultaneous interpreter is not an additional independent management source.

When an answer carries a forecast or thesis, check whether the question supplied the number or desired conclusion. Assent to “my model assumes 50% margin; reasonable?” is an attributed response to an analyst anchor, not automatically independently issued or formal company guidance. Preserve the exchange and qualifiers; seek an explicit comparable disclosure before promoting it into guidance. For unresolved research questions, favor a concise, neutral, single-topic follow-up about the mechanism, prerequisites or timing (for example, what operating changes would support that margin). Follow the substance of the answer rather than forcing a questionnaire; do not score every exchange or treat evasiveness as proof of misconduct.

For each load-bearing item, reuse the existing evidence table or equivalent prose:

| Field | Meaning |
|---|---|
| Source and exchange | Event/period, speaker, original link and verified locator; question premise separate from answer |
| Statement type | Management-reported actual, management explanation, guidance, aspiration, analyst question or researcher inference |
| Metric and scope | Number/range or qualitative statement; currency, percent/basis points, accounting basis, segment/geography/cohort and horizon |
| Conditions and limits | Dependencies, exclusions, uncertainty, timing, partial answer, refusal to disclose or transcription doubt |
| Change and consequence | Comparable prior statement if available; changed assumption or obtainable verification evidence, only for research tasks |

This is a semantic contract, not a required new JSON database. A management-reported actual may feed the existing `reported_fact` class with attribution and source checks; numeric forward guidance uses `management_guidance`. Aspirations, explanations and unanswered questions must not be coerced into factual model inputs. Preserve the original range; label any midpoint or annualization as a derived calculation with its assumptions.

## Numerical And Translation Fidelity

Verify doubtful material numbers, negation, product names, percentages versus percentage points/basis points, currency, time horizon and conditional language against the corresponding recording and slides where accessible. Distinguish “fifteen” from “fifty,” growth from margin, constant currency from reported growth, and gross from net. Numbers that disagree with filings may reflect a different scope or a spoken error: retain both locators, seek clarification/correction and do not silently replace one with the other. Do not guess from plausibility alone.

Chinese translation must preserve “expect,” “target,” “could,” “subject to” and negations without strengthening commitment. Where available, use the original-language statement to resolve an interpreter's or third-party translation's ambiguity. Do not concatenate two language versions as separate disclosures or conflate differing sessions. Retain a short source excerpt for a disputed phrase when permitted. If no audio timestamp exists, cite the actual transcript section or a clearly labeled locally assigned paragraph; never manufacture timestamps or claim to have listened.

## Compare Commitments, Not Tone

For deep research, connect the latest four available relevant earnings cycles to the existing period comparison, adapting to the actual reporting cadence. Do not force four quarterly calls for a semiannual issuer or expand a single-call extraction into history collection. Compare like-for-like metric, scope, accounting basis, horizon and conditions. Record raise/cut/reaffirm/withdraw only with supporting language or a genuinely comparable numerical change; separate newly introduced guidance, a narrowing range, changed perimeter and missing repetition.

Trace prior commitments to current actuals and explanations; a confident tone or a longer answer is not proof of delivery. “Not discussed this time” is not withdrawal, and “we will not disclose” is not evidence that the economics are bad. A refusal can leave an important thesis unresolved without establishing the bearish explanation. Preserve qualifiers that prevent comparison instead of assigning a precise hit rate to incomparable guides.

Research synthesis should answer what was said, what changed, which independent evidence supports or challenges it, which operating/model assumption it affects and what could resolve the uncertainty. Reprints of the same answer do not provide independent confirmation. Missing calls narrow coverage, not permission to abandon accessible filings or fabricate a four-period story.

## Delivery Boundary

For extraction/translation only, deliver the requested text or permitted summary/excerpts, speaker/locator structure and coverage limitations; do not silently replace a transcript request with an investment memo. Respect source access and reproduction limits, and state any resulting gap rather than labeling a summary “verbatim/full.” For a research request, deliver the claim-level synthesis with original citations and preserve accessible raw evidence in the existing authorized workflow. Neither route grants permission for Notion publication, a new archive, persistent monitoring or contacting IR.
