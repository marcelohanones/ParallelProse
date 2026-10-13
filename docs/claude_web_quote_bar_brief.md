# Brief for a web AI: is the verbatim quote evidence, or a pointer?

Paste this whole document. It is self-contained: everything you need is below, and you have no access to the
repository (deliberately — we want an outside read).

## The question, first

ParallelProse prints, per book, **one claim** and **one verbatim sentence** as its backing. Our own check — "every
part of the claim must be supported by that sentence alone" — fails on 16 of 17 cases. We cannot tell whether that is

- **(D) a defect**: the output ships claims whose printed quotation does not support them, or
- **(M) a mis-set bar**: the check applies a standard the design never intended — a pointer, not a proof.

Both readings produce the identical number, so no further measurement of ours can separate them. We need you to argue
which one is coherent with the design described below, and to tell us what we have missed in framing it as a binary.

## 1. What ParallelProse is

A two-book comparison system. Given one literal query, it runs that query against two books independently — Saint
Augustine's Confessions (Pusey translation, 1838) and Guy Debord's The Society of the Spectacle (Knabb, 2002) — and
produces a structured comparison:

- **agreement** — what both books claim in common about the query;
- **disagreement** — where their claims about the same point conflict;
- **each book's own finding** — what that book says, with a **verbatim quotation** as its backing.

It is not a chatbot and not a general research assistant. Retrieval is per book; every quotation is checked
deterministically against the book's own text, and a quotation that is not verbatim in the book is a hard failure.

## 2. Who the output is for — the thing we have never decided

This is the crux and we will not pretend otherwise. The repository uses the word "reader" in three places, and none
of them settles what the reader *does* with the quotation:

- the witness-view export is written so that "the next reader must not inherit" the system's own comparison fields;
- the composer docstring: "the readers take their per-book record from the evidence verdict, not from here";
- the roadmap, on the witness view: "this file's reader is the side whose job *is* the comparison".

The closest thing to a definition of the quotation's role is the composer's own field description:

> quote: **An exact, verbatim excerpt that backs claim_in_passage.**

**"Backs"** carries the whole question:

- **(a) The reader reuses the material.** The claim and its quotation go into someone else's product — an essay, a
  comparison note, an editorial artefact — and the quotation is the evidence a third party would check. Then the
  quotation must *prove* the claim.
- **(b) The reader navigates.** The quotation tells the reader where in the book this comes from, and they go and read
  around it. Then the quotation only has to be real, findable and on-topic — it never had to prove anything alone.

Note the asymmetry in the code: the *machinery* is proof-shaped (deterministic verbatim verification exists because an
inexact quotation is treated as a defect; a "found in book" status was added precisely to distinguish "retrieved but
absent from the chunks" from "invented"), while the *claim format* is synthesis-shaped (a condition, an outcome and a
cause). We suspect the project holds both assumptions at once, and that this contradiction is the real problem. Tell
us if that reading is right.

## 3. How the claim and the quotation are produced today

1. **Retriever** — per book, an agent retrieves passages: several chunks of roughly 400–2000 characters each.
2. **Verdict (E)** — an evidence-only per-book judge decides "ok" (this book answers the query) or "silent", seeing
   only the retrieved chunks and the query, never any draft.
3. **Composer** — one structured LLM call per book (gpt-4o-mini, temperature 0.5) with this prompt:

   > "Given this context {context}, the query {query} and the book mapping {book_map}, write a short (3-4 sentence)
   > factual note on: {query}"

   It fills a schema whose finding field is defined as:

   > claim_in_passage: **What this passage asserts, restricted to the form: when X, Y happens, because Z. If the
   > passage states no cause, write that the cause is unstated — never supply one.**

   and whose quotation field is:

   > quote: **An exact, verbatim excerpt that backs claim_in_passage.**

   **Claim and quotation come from the same call**, so they are born paired.
4. **Quote selection** — a deterministic post-step may *replace* the composer's quotation with a sentence from the
   retrieved chunks that shares the most query content terms, when that sentence scores strictly higher. **The finding
   text is not rewritten.** This step exists to fix the composer quoting a neighbouring sentence or echoing the query.
5. **Verification** — every quotation is checked verbatim against the book. Non-verbatim is a hard failure.

**What the consumer finally sees, per book, is step 3's claim and step 4's sentence. Nothing else.**

## 4. The check, verbatim

The reader-facing check ("quote-alone") is an LLM judge (gpt-4o, temperature 0) with this prompt:

> Finding: {claim}
>
> Quote: {quote}
>
> Split the finding into its separate factual claims about what the book says. For each claim, decide whether the
> quote alone supports it. Judge only against the quote's words: not the rest of the book, not what you know about
> the author. A claim that generalizes, interprets or adds a cause beyond what the quote states is not supported.

with the per-claim field: *"True only if the quote alone, read literally, supports this claim"*. A finding passes only
if **every** claim it is split into is supported. The judge typically splits these findings into 2–6 claims, sometimes
10.

For comparison we also ran a variant identical except that the evidence is the **passage the quotation came from**
instead of the sentence, and a third using **all retrieved chunks**.

## 5. What we measured

Two independent runs of the same code over a 16-entry golden set, 17 findings in run 1 and 15 in run 2 (a book the
verdict calls "silent" produces no finding):

| Evidence given to the judge | run 1 | run 2 |
|---|---|---|
| the quote alone (the reader-facing bar) | 1/17 | 1/15 |
| the passage the quote came from | **12/17** | **9/15** |
| all retrieved chunks | 15/17 | 11/15 |

So in 11 of 17 cases the finding is supported by the passage it came from, yet not by the sentence printed as its
backing.

Other measurements:

- **Composer's own sentence vs. the replacement.** On the 7 sides where the quotation had been replaced, we re-ran
  the quote-alone check with the composer's original sentence: **0/7 passed, exactly as the replacement did (0/7).**
  So the replacement is not what causes the reader-facing failure.
- **At passage level**, pooled: the composer's own sentence 14/17 (82%), the replacement 7/15 (47%), Fisher exact
  p = 0.062 — suggestive, confounded (replacement only happens when the composer's sentence scores worse on query
  terms, so it is not a random sample).
- **Failure classification**, the 16 quote-alone failures: 8 = the sentence is from the right passage but too small
  for the claim; 5 = the wrong sentence entirely (a lexical match on a query word); 1 = the claim exceeds the passage
  too; 2 = the judge being strict about paraphrase.
- **Can each claim be paired with a sentence at all?** We split the 17 findings into their claims and asked, for each
  claim, whether some single sentence among the retrieved chunks states it: **55 of 57 claims (96%) found one**, and
  15 of 17 findings were fully pairable. The two failures were genuinely multi-sentence claims. Note this probe is an
  oracle — the model saw the finished claim and every retrieved sentence at once.
- **Judge quality, out of domain.** Against RAGTruth (a public corpus of ~18,000 RAG responses with human word-level
  hallucination spans), 60 hallucinated + 60 clean held-out responses: **sensitivity 88%, specificity 80%**. By task:
  summarisation 79%/94%, QA 71%/82%, data-to-text 97%/**50%**.
- **Stability.** Between the two runs of identical code, 5 of 15 shared sides flipped verdict. Run-to-run agreement
  67%.

**Caveats we already know.** The golden set is 16 entries. The judge was validated in-domain against 27 human-labelled
findings that are 26 unfaithful and 1 faithful — so its in-domain false-alarm rate is essentially unmeasured, and the
80% figure above is out-of-domain. The passage-level and pairing probes are LLM runs, not human-labelled. Any single
number here carries roughly ±2 sides of noise.

## 6. Three real cases

### Case 1 — the right sentence exists, and was not printed (g07 A, passage bar PASS)

- **Query:** Why is the heart restless?
- **Claim:** "When the heart seeks fulfillment in worldly things, it remains restless, because true peace is found
  only in God."
- **Printed sentence (the composer's own choice, not replaced):** "Behold, these things pass away, that others may
  replace them, and so this lower universe be completed by all his parts. But do I depart any whither? saith the Word
  of God."
- **In the same retrieved passage:** "…there is the place of rest imperturbable, where love is not forsaken, if itself
  forsaketh not."
- **Elsewhere in the retrieved chunks, sentences the pairing probe matched to the claim's two parts:**
  "There is no rest, where ye seek it." and "Rest in Him, and ye shall be at rest."

The claim is a two-part proposition. Each part has a sentence in the retrieved material. The printed sentence is
adjacent in theme but states neither part.

### Case 2 — the composer's sentence carries one part of a two-part claim (g08 A, passage bar FAIL)

- **Query:** What does the voice of a child say to a man weeping in the garden?
- **Claim:** "When a man weeps in the garden, a child's voice calls him to 'Take up and read', suggesting he should
  seek solace in scripture."
- **Printed sentence (a replacement):** "for something I suppose I had spoken, wherein the tones of my voice appeared
  choked with weeping, and so had risen up."
- **Composer's own sentence, which the replacement displaced:** "I heard from a neighbouring house a voice, as of boy
  or girl, I know not, chanting, and oft repeating, 'Take up and read; Take up and read.'"
- **Elsewhere in the retrieved chunks:** "I cast myself down I know not how, under a certain fig-tree, giving full
  vent to my tears" and "interpreting it to be no other than a command from God to open the book, and read the first
  chapter I should find."

Note the shape: the claim's three parts each have a sentence. The composer chose the sentence for part two. The
replacement chose a sentence for "weeping". Neither proves the whole.

### Case 3 — an off-topic replacement, and a judge strict on paraphrase (g03 A, passage bar FAIL)

- **Query:** Which sense is set above all the others?
- **Claim:** "When the soul seeks knowledge, it primarily uses the eyes, which are considered the most important sense
  for perceiving the world and understanding truth."
- **Printed sentence (a replacement):** "Behold, these things pass away, that others may replace them, and so this
  lower universe be completed by all his parts." — **topically unrelated to the claim.**
- **Composer's own sentence, which the replacement displaced:** "The seat whereof being in the appetite of knowledge,
  and sight being the sense chiefly used for attaining knowledge, it is in Divine language called The lust of the
  eyes."
- **Elsewhere in the retrieved chunks:** "And so the general experience of the senses, as was said, is called The lust
  of the eyes, because the office of seeing, wherein the eyes hold the prerogative, the other senses by way of
  similitude take…"

Here the composer's own sentence states parts one and two almost exactly, the third part is stated by a different
sentence, and the *printed* sentence states nothing relevant. All three claims were nonetheless failed by the
quote-alone judge.

## 7. What we already tested and ruled out

- **"The composer invents content."** Ruled out. Against the passage it read, 12/17 findings are fully supported.
- **"Lexical quote selection is the main cause."** Ruled out as the lever: restoring the composer's own sentence on
  the 7 replaced sides changes nothing at the reader-facing bar (0/7 both ways). It remains a real defect for
  *relevance* — Case 3's printed sentence is unrelated to its claim.
- **"Tightening the claim to the passage will fix it."** Tested. The claim field was rewritten to require a claim
  restricted to the passage, and the reader-facing number did not move at all (1/17 before, 1/17 after, on the same
  sides). Our reading: that change *specified* the condition-outcome-cause shape, which is what manufactures
  multi-part claims in the first place.

## 8. Options currently on the table

1. **Print the sentence inside its surrounding paragraph**, so the reader's proof unit is the passage and the sentence
   is the most direct line in it. Cheap; changes the contract from "this sentence proves it" to "this passage
   contains it".
2. **Make the claim one proposition** — the one its sentence states. Cheap to write, but it discards the book's
   position as a synthesis; and if "one proposition" is read as "a shorter, more abstract claim", it makes the pairing
   worse, not better.
3. **Several (claim, sentence) pairs per book.** The 96% pairing result says the sentences exist. Keeps the content,
   changes the output schema. Nothing downstream of this output has ever run on real data, so the migration cost is
   at its lowest now.

## 9. What we want back

We are not looking for agreement; we are looking for falsification.

1. **Argue the strongest case for (D) and for (M)** — then say which is coherent with the design as described, and
   where that description is self-contradictory.
2. **Tell us what is wrong with our framing.** We suspect the binary itself may be false: perhaps a quotation can
   legitimately serve as a pointer *while* the claim is still required to be a single proposition. If there is a
   third reading, name it.
3. **Audit the inferences.** Given the sample sizes, the judge's measured error rates, and the caveats in section 5,
   which of our conclusions are actually justified? Specifically: is "the composer is grounded but the printed
   sentence isn't" supported, or are we over-reading 12/17 from a 16-entry set?
4. **If the design question cannot be settled by argument, say what measurement would settle it.** Be concrete about
   what would have to be labelled by a human, and how much of it.
5. **Name the consequence we are not seeing.** In particular, if the answer is (M), what should happen to the
   machinery built on the assumption that the quotation is evidence?
