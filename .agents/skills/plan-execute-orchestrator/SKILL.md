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

**Human validation:** **Never** proceed with implementation without explicit user approval of the plan.

### Phase 3: Delegation and Subagent Execution
Delegate the execution of the plan to a separate subagent with a fresh context window---**do not** execute it yourself. Instruct the subagent that the plan provided is final and approved, and that its sole job is strict execution without re-planning.

When spinning up a subagent, pass *only* the specific slice of the plan it is responsible for, alongside the exact target file paths. Use `/agents` to monitor background workers. Collect their finalized assets, verify their work, and merge the results into the global state.