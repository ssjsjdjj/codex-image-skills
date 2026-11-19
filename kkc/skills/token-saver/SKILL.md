---
name: token-saver
description: Reduce avoidable token and API cost through task-aware model selection, context hygiene, concise responses, and disciplined tool use. Apply as an advisory policy on every turn. Actual savings vary by agent, model, provider, cache behavior, and workload; measure results instead of assuming a fixed percentage.
---

# Token Saver

Token Saver is an advisory efficiency policy for AI agents. Its goal is to reduce unnecessary input, output, and tool-call overhead while preserving task quality.

The primary objective is not the smallest prompt. It is the lowest **cost per successful task**, including retries, rereads, and repair work.

## 1. Classify task risk before choosing a model

Use the least expensive model that can reliably complete the task.

### Low-risk routine work

Examples:

- greetings and acknowledgments;
- simple translations;
- direct factual lookups;
- formatting or mechanical transformations;
- routine tool-result interpretation.

Prefer a small or low-cost model when the host supports model switching.

### Medium-risk structured work

Examples:

- multi-step but familiar workflows;
- standard file operations;
- simple code edits with clear tests;
- summarization and comparison;
- ordinary debugging with localized scope.

Prefer a balanced model.

### High-risk or ambiguous work

Examples:

- architecture and security decisions;
- complex debugging across multiple systems;
- large refactors;
- nuanced analysis;
- tasks with expensive failure or unclear success criteria.

Use a stronger model and preserve more context.

### Routing rules

- Do not switch models only because a prompt is short or long.
- Consider ambiguity, failure cost, verification difficulty, and required reasoning.
- Keep the current model when the host cannot switch safely.
- Do not claim savings from routing unless actual provider usage and task outcomes are available.

## 2. Keep only useful conversation state

When a conversation becomes long:

1. preserve names, constraints, decisions, unresolved questions, and next actions;
2. drop resolved branches that no longer affect the current task;
3. avoid repeating the user's request back to them;
4. store durable project facts in files when the workspace supports it;
5. keep exact source text when wording, legal meaning, code, or numerical detail matters;
6. do not summarize aggressively if the task may depend on earlier exceptions or edge cases.

Suggested compact state:

```text
[Goal]
[Confirmed constraints]
[Decisions]
[Current artifacts]
[Open risks]
[Next action]
```

## 3. Avoid repeated reads and repeated results

Before reading a file, URL, message, or tool result:

- check whether the same content is already available;
- prefer a targeted range, symbol, diff, or search result over a full file;
- request only changed sections when prior content is still valid;
- batch related reads when it reduces repeated setup overhead;
- avoid reading a file again only to confirm content that was just written.

Reread when correctness requires it, especially after external changes, concurrent edits, or failed writes.

## 4. Match output length to task value

- yes/no or confirmation → one direct line;
- simple task → a few complete sentences;
- complex task → structured detail with no ceremonial filler;
- do not restate large inputs unless transformation or verification requires it;
- do not generate tables when a short explanation is clearer;
- do not add generic openings or closings that provide no information.

Never trade away necessary warnings, assumptions, evidence, or error details merely to shorten the answer.

## 5. Use tools economically

- combine independent operations when the tool supports safe batching;
- avoid speculative calls that do not affect the answer;
- use search before broad file reads;
- prefer diffs and metadata over complete artifacts;
- avoid screenshots unless visual inspection is required;
- avoid repeated fetches of unchanged resources;
- preserve separate calls when sequencing, permissions, or failure isolation matters.

## 6. Protect cache-friendly prompt structure

When the host or provider supports prompt caching:

- keep stable instructions at the beginning;
- place changing task data later;
- avoid rewriting equivalent system instructions every turn;
- avoid injecting timestamps, random IDs, or reordered tool definitions into stable prefixes;
- load only relevant tools when dynamic tool loading is supported.

Cache behavior is provider-specific. Treat local token estimates and billed cache usage as different measurements.

## 7. Detect false savings

An optimization may have removed important detail when the agent:

- repeats the same tool call;
- rereads the same file with a broader range;
- asks for the original content;
- reruns a command because evidence was missing;
- produces a lower-quality or unverifiable result.

When this occurs:

1. recover or reread the original content;
2. complete the task correctly;
3. treat the earlier compression as a failed optimization;
4. do not report the initial token reduction as a successful saving.

## 8. Measurement discipline

When usage data is available, distinguish:

- estimated tokens;
- provider-reported input tokens;
- cached input tokens;
- reasoning tokens;
- output tokens;
- retries and repeated tool calls;
- task success.

Use provider-reported usage as billing truth. Evaluate the full task, not a single request.

## Pre-response checklist

- [ ] Is the selected model appropriate for task risk?
- [ ] Am I carrying resolved or duplicated context?
- [ ] Can I use a targeted read, diff, or search instead of a full read?
- [ ] Are planned tool calls necessary and safely batchable?
- [ ] Does the answer length match the task?
- [ ] Could shortening or compression remove evidence needed later?
- [ ] Can task success be verified?

## Scope

This skill provides behavior guidance. It does not by itself guarantee interception of API requests, provider-level cache control, exact token accounting, or a fixed savings percentage. Those capabilities belong to the planned Token Saver Doctor, Gateway, Proof Ledger, and Quality Guard described in the repository roadmap.
