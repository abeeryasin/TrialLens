# Decisions & Learning Log — TrialLens

Dated entries capturing real decisions and why — a decision happens,
then it gets written down before moving on, so it isn't lost when
context resets.

## 2026-08-25 — Domain considered and shelved: maternal-health / Three Delays

Explored a Maternal Death Surveillance & Response project built on the
WHO "Three Delays" framework, using the WHO GHO API (verified live,
works) plus PDHS/MICS microdata (real but gated behind manual
registration, not autonomously fetchable, non-redistributable) plus
literature grounding for the framework (corrected from an initial,
wrong assumption that de-identified Pakistani case narratives are
publicly available — they aren't; verified via search, found none).
Reframed to literature-grounded proxies rather than case-level data.
Ultimately shelved — a second candidate (TrialLens) matched a genuinely
different set of unpracticed skills more directly. Logged as a
legitimate future project, not discarded.

## 2026-08-25 — Domain chosen: TrialLens

Chose a clinical-trial intelligence project after auditing what was
already genuinely demonstrated versus what remained unpracticed:
knowledge graphs, autonomous scheduled operations, multi-agent
handoff/parallel execution, and real MCP plus database read-only
enforcement. Verified against ClinicalTrials.gov's real, public,
no-auth v2 API (live-tested 2026-08-25, ~50 req/min, public domain
data) before committing to it.

## 2026-08-25 — Persona: clinical researcher, not a one-time patient search

A patient searching once wouldn't justify the scheduled-monitoring,
change-detection, or review-queue features at all — just a search box.
A researcher tracking a therapeutic area over time is what makes the
multi-agent, autonomous shape of the project actually necessary rather
than decorative.

## 2026-08-25 — Notification mechanism: Resend, not SendGrid

Checked both rather than assuming either was still free. SendGrid
dropped its permanent free tier in 2023 (now a 60-day trial only — no
good for something meant to run indefinitely). Resend has a real
permanent free tier (100 emails/day, 3,000/month, no expiration) — far
more than one daily digest email needs. Chosen for that reason.

## 2026-08-26 — External product spec: adopted in part, corrected in part

A detailed product spec from another AI model proposed the
five-capability framing (Discover/Understand/Monitor/Explore/
Investigate), "deterministic first, AI second, agents third," using
"potential fit" instead of "patient eligibility" language, and building
evaluation cases from day one — all adopted, genuinely stronger than
what existed before.

Pushed back on three things: (1) its architecture diagram proposed a
FastAPI layer built speculatively, "for later," with no real consumer
lined up — resolved by making FastAPI a real, load-bearing boundary
from day one instead: the frontend and the scheduled fetcher both
genuinely go through it, and it's also where read-only enforcement for
query-side agents lives, since there's an explicit intent to learn
FastAPI regardless of whether the architecture strictly requires it
yet. (2) Its proposed "vector store" risked building unrelated
document-retrieval infrastructure this project doesn't need — clarified
this is a legitimate, different use case (semantic search over a local
trial cache, not long-document grounding) but sequenced for once real
cached data exists, not the walking skeleton. (3) Its claim that
"ClinicalTrials.gov itself maintains record versions" was checked
(true — a separate archive site, plus a per-trial RSS feed worth
investigating later) rather than accepted at face value, since it was
being used to justify the whole monitoring feature's legitimacy.

Also worth naming as its own lesson: the document's own later section
warned against building everything at once, immediately after many
earlier sections describing almost exactly that. Read a big
AI-generated proposal's own later caveats against its earlier scope
before adopting either.

## 2026-08-26 — Future literature integration: logged, not built

Pulling supporting literature for a given trial via a separate
document-Q&A capability is a genuine, non-forced idea — trials and
literature about the same interventions are actually connected in the
real world. Deferred anyway: this project's own core capabilities don't
need it to work, and a cross-tool integration now would add real
complexity before this project stands on its own. Logged as a future
idea, not built now, not forgotten.

