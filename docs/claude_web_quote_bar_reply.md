# Item — quote bar: answer back from the web AI

Pasted by the user, unedited except for the header. Responds to `docs/claude_web_quote_bar_brief.md`.

---

# Short answer

The binary is false. The design is not coherently one thing. It has an **evidence-shaped label** ("quote: … backs claim_in_passage"), a **provenance-shaped machinery** (verbatim hard failure, found-in-book status), and a **synthesis-shaped claim format** (when X, Y happens, because Z; 3–4 sentence note). A single sentence cannot normally be the whole evidence for a multi-part causal synthesis.

So the strongest reading is not (D) or (M) alone. It is a third reading:

> **The quote is a verbatim anchor/pointer into a passage, and the passage is the evidence unit.**
> If you want the quote itself to be evidence, the claim must be atomic, or you must print multiple (claim, quote) pairs.
> If you want the claim to remain a synthesis, you cannot print one sentence as its "backing" without also exposing the passage.

Under the current schema, the output is defective *because it says "backs" while behaving like a pointer*. Under a corrected pointer/anchor schema, the quote-alone check is mis-set. The real problem is the mismatch between the claim unit and the evidence unit.

---

## 1. Strongest case for (D): defect

The quote field is defined as:

> **"An exact, verbatim excerpt that backs claim_in_passage."**

The consumer sees only the claim and that sentence. Nothing else. The claim is written in a truth-apt, causal, condition–outcome form. A careful reader checking the claim would reasonably ask: *does this sentence prove the claim?* That is exactly what the quote-alone judge asks.

Under that contract:

- Case 3 is not ambiguous: the printed sentence is topically unrelated to the claim.
- Case 1 has the right sentence elsewhere, but not printed.
- Case 2 has the composer's own sentence carrying one part of a three-part claim, but the replacement chose another sentence for "weeping."
- The replacement step optimizes query-term overlap, not entailment. That is a bug if the quote is evidence.
- The fact that the composer was grounded in the passage does not cure the output. The printed backing is still wrong.
- The pairing probe suggests proper sentence-level pairs often exist. The system simply does not print them.

So (D) says: the system is shipping claims whose printed quotation does not support them. The fix is not to lower the bar. The fix is to change the output contract: atomic claim + entailing quote, or multiple pairs, or print the passage.

The strongest point for (D) is that the field description itself uses "backs." If the project meant "points to," it should not have said "backs."

---

## 2. Strongest case for (M): mis-set bar

ParallelProse is a comparison system, not a citation engine. The composer prompt asks for a 3–4 sentence factual note. The schema forces a condition–outcome–cause synthesis. That is not the content of one sentence. It is a summary of a passage or several chunks.

Under the pointer reading:

- The quote tells the reader where in the book this comes from.
- Verbatim verification ensures the pointer is real and findable, not invented.
- The replacement step chooses a sentence with high query-term overlap. That is a relevance heuristic, not a proof heuristic.
- The quote-alone judge asks one sentence to entail a multi-sentence synthesis. That is a category error.
- Passage-level support is much higher: 12/17 and 9/15.
- The pairing probe says 55 of 57 claims have some sentence among retrieved chunks that states them. The material exists; the displayed unit is too small.

So (M) says: the 16/17 quote-alone failure is expected. It is not a defect in the output; it is a defect in the check. The right bar is: the quote is verbatim, on-topic, and from a passage that supports the claim. The reader navigates to the passage.

The strongest point for (M) is that the claim format itself is synthesis-shaped. You cannot ask a single sentence to prove a synthesis.

---

## 3. Which is coherent with the design?

The design as described is self-contradictory. Your suspicion is right.

The contradiction is here:

- **Evidence-shaped label:** "quote backs claim_in_passage."
- **Provenance-shaped machinery:** verbatim hard failure, found-in-book status.
- **Synthesis-shaped claim:** when X, Y happens, because Z.
- **Pointer-shaped replacement:** pick the sentence with the most query terms, not the most entailment.

The "reader" references do not settle it. Witness view, composer docstring, roadmap: none define whether the quote is proof or navigation. The closest definition is "backs," but "backs" is doing all the work while the pipeline behaves as if it means "points at."

So neither (D) nor (M) is fully coherent with the whole design.

- If you isolate the field description and hard verbatim check, (D) is coherent.
- If you isolate the composer prompt, claim schema, and lexical replacement, (M) is coherent.

The coherent third reading is:

> **The quote is an evidentiary pointer/anchor.**
> It is not standalone proof. It is not a mere navigation aid either.
> It must be a verbatim, on-topic excerpt from a passage that supports the claim.
> The passage, or a set of claim–sentence pairs, is the evidence unit.

Under that reading, the current output is still defective because it prints the anchor as if it were the evidence and hides the passage. The quote-alone check is also mis-set because it tests the anchor for a job only the passage can do.

The binary you framed assumes two options: quote = proof, or quote = pointer. The missed dimension is: **what is the claim unit?** A synthesis claim can be paired with a pointer, but then you must not call the pointer "backing." An evidence quote can back an atomic claim. A synthesis claim needs a passage or multiple quotes.

---

## 4. Audit of your inferences

Your data are suggestive, but most of the numbers are too small and too LLM-dependent to carry the weight you are putting on them.

### "The composer is grounded but the printed sentence isn't"

This is partly supported, but not as cleanly as you state.

- **Printed sentence isn't enough:** Strong. Quote-alone is 1/17 and 1/15. The cases show obvious mismatches. Even with judge error, 16/17 failures is too many to explain by noise alone.
- **Composer is grounded:** Moderate. Passage-level is 12/17 and 9/15. Pooled that is about 21/32 ≈ 66%, with a wide 95% interval roughly 48–80%. That suggests many findings are supportable by more than the printed sentence. But the passage-level check is an LLM judge, not human-labelled. It may be lenient.
- **Composer invents content:** You say "ruled out." That is too strong. Better: "Invention is not the main explanation for the quote-alone failure." With 16 entries and no human labels, you cannot rule out a nontrivial invention rate.
- **Pairing probe:** 55/57 is impressive, but it is an oracle. The model saw the finished claim and every retrieved sentence. It shows sentences exist under a generous matching procedure. It does not show that a single sentence can be selected without synthesis, or that the composer used it.
- **Replacement not main cause:** Fair for the quote-alone bar, but n=7. 0/7 both ways is tiny. It does not prove replacement is harmless. Case 3 shows it can cause relevance failures.
- **Tightening claim to passage didn't move:** Suggestive that claim shape is a major cause. But n=17, one prompt revision, same sides. It is not decisive.
- **Judge quality:** Out-of-domain specificity 80% means if all 17 were truly supported, you would expect about 3 false alarms, not 16. So the failure is probably real. But the in-domain false-alarm rate is essentially unmeasured: 26 unfaithful, 1 faithful. You cannot estimate false alarms from one faithful example.
- **Stability:** 67% run-to-run agreement means per-side verdicts are noisy. The near-zero quote-alone result is stable enough to say there is a systemic mismatch. The 12/17 vs 9/15 difference is not stable enough to make fine distinctions.

So the justified conclusion is narrower:

> The displayed sentence often does not support the synthesized claim. The larger passage often does. The composer is probably not the main locus of the defect; the pairing/display unit is. But the exact rates need human labels.

---

## 5. What measurement would settle it

If the question is "is the quote evidence or a pointer?", no measurement alone can settle it. That is a product/contract question. You can measure what readers do with it, but you still have to decide what you want them to do.

If you want to settle whether the current output is defective under a chosen contract, do this:

### A. Contract study

Give intended readers three conditions:

1. claim + printed quote only
2. claim + passage containing the quote
3. claim + multiple (claim, sentence) pairs

Ask them to: verify the claim, find the supporting passage, decide whether they would cite the quote as evidence, write a short comparison note.

Measure success, time, confidence, and error rate. This tells you which evidence unit readers actually need.

### B. Human labelling of current output

Sample 100–200 findings from the real distribution. Use 3 human annotators. For each finding: split it into atomic claims; for each atomic claim, label supported by printed quote alone / by the passage the quote came from / by all retrieved chunks / is there a single sentence in the retrieved chunks that states it. Adjudicate disagreements. Report inter-annotator agreement. To estimate a pass rate near 50% with ±10%, you need about 100 claims per condition. To estimate a near-zero rate tightly, you need several hundred. But even 100–200 findings would be a large improvement over 16.

### C. In-domain judge validation

Label at least 50–100 faithful and 50–100 unfaithful examples in your domain. Since faithful examples may be rare, oversample passage-level passes and have humans confirm. This gives you a real false-alarm rate. Without it, you cannot separate judge strictness from genuine mismatch.

### D. Prototype multiple pairs

Take 50 findings. Have humans or an LLM propose multiple (claim, sentence) pairs. Human-label each pair. If the 96% pairing result survives human labelling, option 3 is viable. If not, it is not.

The key point: **your 16-entry golden set can tell you there is a problem. It cannot tell you which contract is correct or give you reliable pass rates.**

---

## 6. The consequence you are not seeing if the answer is (M)

If the quote is a pointer, then much of the machinery built on "quote as evidence" is misnamed, not necessarily useless.

- **Verbatim verification stays.** A pointer must be exactly findable. Non-verbatim is still a hard failure.
- **Found-in-book status stays.** It distinguishes a real pointer from a hallucinated one.
- **Quote-alone judge should be retired as a gate.** It can remain as a diagnostic for "could this quote be used as evidence?" but it should not fail pointer-mode output.
- **The schema must change.** "quote backs claim_in_passage" must become "anchor quote" or "excerpt from supporting passage," and the passage must be exposed.
- **The replacement step is optimizing the wrong objective.** Query-term overlap is a relevance heuristic. For a pointer, you want a sentence that is central to the supporting passage and useful for navigation, not merely lexically close to the query. Case 3 is the warning.
- **The comparison fields are at risk.** Agreement/disagreement are built from synthesized claims. If quotes are pointers, the comparison's evidence basis is the passage, not the quote. You may be comparing two system syntheses rather than two book positions. The witness-view instruction "the next reader must not inherit the system's own comparison fields" already hints at this worry.
- **The biggest unseen consequence:** if you adopt (M) but keep printing one sentence under "backs," you are shipping a pointer with a proof-shaped label. That is worse than either pure (D) or pure (M). Readers will treat the quote as evidence, and it will often fail them. You must either change the label and expose the passage, or change the output to make the quote actually evidentiary.

So the design question is not "is the quote evidence or a pointer?" It is "what is the evidence unit, and does the output expose it?" The current answer is inconsistent: the claim is a synthesis, the quote is a pointer, and the label says evidence. Fix that mismatch before you fix the judge.
