---
name: plan-execute-orchestrator
description: Coords complex multi-step tasks using a Plan-Execute workflow. Use this whenever the user asks for multi-file generation, deep architectural changes, or complex debugging.
---

# Plan-Execute Orchestrator

## Goal
To orchestrate multi-step engineering tasks safely and effectively by centralizing the planning phase and delegating specific tasks to fresh execution contexts.

## Instructions

### Phase 1: Research & Context Gathering
Do not draft a plan blindly. Scan the codebase using read-only tools (`view_file`, `grep_search`) to verify the current technical stack, data schemas, and existing files.

### Phase 2: Write the Plan
The `Implementation Plan` is the set of steps to implement the requested feature or change. The plan **should not** contain any blocks of code, but it is acceptable to name imports to add/remove, functions/constants to create or update, or algorithms to use. It should only contain a high-level list of steps, and should be clear enough to proceed with implementation without needing any assumptions. It should not leave any questions open.

**Proposed changes:** This section of the plan should be separated by file. Each subsection must mention the file to be updated or created, as well as the list of modifications to make to the corresponding file. Be specific, and make sure to say *where* in the file code should be added, updated, or removed.

**Verification:** This section of the plan is optional. If present, it should be separated logically by test to perform. Each test should have an unambiguous set of tests to be performed, as well as their expected results.

You may use `Task Lists` as you see fit.

### Phase 3: Human validation
**Never** proceed with implementation without explicit user approval of the plan.

If the user requests changes or answers open questions, you **loop back to Phase 2** and proceed as follows:
1. Acknowledge the changes/answers.
2. Output an updated `Implementation Plan` to the user.
3. Ask the user for explicit approval of the revised plan.
4. STOP. Do not invoke Phase 4 subagents or call any execution tools until the user replies with a clear confirmation.

Treat any response containing feedback as a rejection of the current plan, requiring a loop back to this validation step.

### Phase 4: Delegation and Subagent Execution
At this point, you must hand over the task of implementing the plan to a separate subagent with a fresh context window. Your role is simply orchestration: **do not** implement the plan yourself and **do not** generate any code blocks yourself. Instruct the subagent that the plan provided is final and approved, and that its sole job is strict execution without re-planning.

Delegate the *Proposed changes* section of the plan to one subagent. Once it completes its work, delegate *verification* (if present) to a separate subagent. If verification fails, return to Phase 1 and revise the plan before delegating again. This revised plan **still requires human approval** before implementation.

When spinning up a subagent, pass *only* the specific slice of the plan it is responsible for, alongside the exact target file paths. Use `/agents` to monitor background workers. Collect their finalized assets, verify their work, and merge the results into the global state.