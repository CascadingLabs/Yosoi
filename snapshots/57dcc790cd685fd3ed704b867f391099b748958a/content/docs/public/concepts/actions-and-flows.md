---
title: 'Actions and Flows'
description: 'Separate a browser recipe from its execution resources.'
order: 0
---

# Actions and Flows

An Action describes one operation, such as navigating, clicking, entering text or checking evidence. A Flow orders those operations into a recipe.

Authoring does not perform browser I/O. Invocation selects ownership and Policy, validates the recipe and runs it.

## Describe, invoke, inspect

1. Describe the ordered Actions.
2. Choose whether a failed prerequisite stops the invocation.
3. Invoke the Flow with managed resources or borrowed Work.
4. Inspect the terminal outcome and step receipts.
5. Verify the business result with the checks the recipe needs.

A recipe can be reused. Managed invocation owns its temporary Session and Work. Borrowed invocation uses Work already held by the caller.

## Checks and waits

An immediate assertion checks current evidence. Until waits for supported evidence within a bounded scope. A sleep delays execution but does not prove that a desired state arrived.

The default can continue after recoverable failures and return `completed_with_issues`. Dependent actions need explicit failure behavior. A checkout task should stop when its prerequisite cart check fails.

A timeout after a click can leave its effect unknown. Cancellation does not roll that effect back. Keep receipts and inspect domain evidence before retrying.

See [Flows](../sdk/flows.md) and [Outcomes](outcomes.md).
