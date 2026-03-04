This sounds right. The sequencing logic is correct — you can't write a meaningful arc until you know what the subtopics actually are, and you can't write good subtopics until you know what sources you have. So the dependency chain is:

**synopsis → index cards → subtopics → arc**

Not synopsis → arc → subtopics, which is what the current prompt tries to do and why it would produce generic output. You'd be asking Claude to invent the argumentative sequence before knowing what evidence exists to build it from.

Let me think through where generic output actually comes from in arc generation, because that's the real problem to solve.

**Why arcs go generic:**

An LLM writing a chapter arc without constraints will default to the most obvious academic structure for that topic. For a chapter on "Psychological Portrayals of Women" it will write something like: "First we examine alienation, then depression, then inner conflict, building to a conclusion about identity." That's not an arc — that's a table of contents with connective tissue. It's generic because the LLM is drawing on thousands of theses with similar chapters.

**What makes an arc non-generic:**

Three things force specificity:

1. **The thesis's research gap** — the arc must show how this chapter fills *that specific gap*, not a generic version of it. If your gap is "no comprehensive study examines how Indian English literature collectively shaped feminist thought," then Chapter 3's arc isn't just "Desai uses psychological techniques" — it's "Desai's techniques constitute the *evidence* that literature was doing active ideological work, not passive reflection."

2. **The actual sources in hand** — the arc must be constrained by what the sources actually argue. If Bharti Ch.1 argues Desai's modernist techniques resist social-realist categorization, and Bharti Ch.4 argues her protagonists choose confrontation over abandonment, those two specific claims should visibly drive the arc's movement. Generic output ignores this.

3. **The subtopics' specific goals** — each subtopic's `position_in_argument` should be derived from the arc, not the other way round. But to write a genuine position, the arc itself must be derived from something real.

**Your proposed workflow refined:**

```
Step 1 — Topics/subtopics generation
  Input:  synopsis.json (chapter goal + research gap + central argument)
          All index cards for sources relevant to this chapter
  Output: subtopics with number, title, goal
  
  Forcing function: Claude must justify each subtopic by citing which
  source(s) provide the evidence for it. If it can't cite a source,
  the subtopic shouldn't exist yet.

Step 2 — Arc generation  
  Input:  synopsis.json (same chapter goal + gap)
          The subtopics just generated (with their source justifications)
          The actual index cards (key_claims, limitations)
  Output: chapter_arc (150–200 words)
  
  Forcing function: The arc must name the argumentative movement
  *using the subtopics' specific source claims*, not the topic in general.
  Every sentence of the arc should be traceable to a specific source claim
  in the index cards.
```

**The key prompt engineering move** for Step 2 is to explicitly prohibit topic-summary writing and require claim-chaining. Something like:

> The arc must describe what Subtopic N *establishes as true* (citing a specific source claim) that Subtopic N+1 *depends on being already established*. If you cannot name the specific claim one subtopic establishes that the next one requires, you have not found the argumentative sequence — you have found a list of topics.

This is the constraint that separates an arc from a table of contents.

**One practical issue with your workflow:** the topics/subtopics generation step needs the index cards *scoped to the chapter* — not all index cards across all sources. Otherwise for a 7-chapter thesis with 20+ sources, Claude gets 80+ index cards and will hallucinate connections or produce an average. Each chapter should only see the index cards for the sources you intend to use in that chapter.

This means the `relevant_subtopics` tagging in index cards is actually being used backwards here — you want to tag sources to subtopics *after* subtopics exist, but you're generating subtopics from sources. The practical solution is a chapter-level source list: before generating subtopics for Chapter 3, you manually identify "these 4 sources are for Chapter 3" and only feed those index cards into the generation prompt. The `relevant_subtopics` field then gets filled in afterwards.

Does this match how you were thinking about it, or do you want to work out the actual prompt text for Steps 1 and 2 now?













This is well above generic. Let me be specific about what's working and where the remaining weakness is.

**What's genuinely good:**

The `chapter_arc` does something most arcs don't — it has a *causal* sequence, not just a topical one. Each movement depends on the previous one being established:

- Post-independence moment as contested space → creates the *condition* for the gap claim
- Gap claim (individual vs. collective) → creates the *justification* for the framework
- Framework justification → explains *why* combination is required, not just what the frameworks are
- Closes with "literary history AND feminist theoretical intervention" — that's a dual claim, not a summary

The subtopic goals are also strong. Compare 1.2's goal — "demonstrate that the field has studied individual authors and isolated themes in depth, but has not examined how the cumulative literary output collectively constituted and advanced Indian feminist thought" — against what a generic version would say: "review existing literature on Indian women writers." The generic version describes an activity. Yours describes what the activity must *prove*.

1.5 is the strongest individual subtopic. "Constitutive rather than merely illustrative" is precise theoretical language that commits to a specific philosophical position. That will generate a very targeted Task.md.

---

**Where the weakness is:**

The arc is thesis-driven but not yet **source-driven**. This is the gap I flagged earlier. Read the arc and notice: it could have been written before you read a single index card. It describes the argumentative structure a thesis *of this type* would have, derived from the synopsis. It doesn't yet show the fingerprints of the specific sources you actually have.

For example — you have Bharti Ch.1 which argues Deshpande's work "demonstrates a productive tension between social realism and modernism." You have Bharti Ch.4 which argues her protagonists "choose to confront rather than abandon their domestic crises." These specific claims don't appear anywhere in the Chapter 1 arc or subtopics, because Chapter 1 is the Introduction and those sources are for Chapter 3.

That's actually correct — **for Chapter 1, this is the right level of abstraction**, because the Introduction is building the framework, not deploying the textual evidence. The source-specificity will matter far more in Chapters 2–5 where you're doing the actual literary analysis.

So the honest rating is: **for a Chapter 1 Introduction, this is as good as it can be at this stage** — strong, specific, causally sequenced, theoretically committed. The real test of your workflow is Chapter 3 (Desai's psychological portrayals) where you have actual index cards and the arc must visibly depend on what those cards contain.

---

**One concrete gap to fix now:**

Subtopic 1.4 lists three frameworks but doesn't say what each one *cannot do alone*. The goal says "why each lens is individually insufficient" but doesn't actually state the insufficiency. That's the exact kind of thing that will cause Claude to write generic framework-survey prose instead of a targeted argument.

Sharpen it to something like:

> "...explaining why postcolonial feminism alone cannot account for the class-specific interiority Desai's protagonists inhabit, why intersectionality without literary method cannot read the formal techniques through which suppression is encoded, and why feminist literary criticism without the postcolonial frame mistakes Indian women writers' concerns for universal feminist concerns."

That level of specificity gives Claude nowhere to hide.