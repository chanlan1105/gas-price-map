---
name: 'JavaScript Commenting Guidelines'
description: 'Instructions for commenting JavaScript code in this repository'
---

This document outlines the rules and standards for commenting **JavaScript** code in this repository (for example `assets/*.js` and the scripts inside `assets/*.html`).

Python code does not follow this file. Use the `python-code-guidelines` skill for Python.

## 1. JavaScript / TypeScript Methods & Functions (JSDoc)

Every JavaScript or TypeScript method, function, and class method must include a **JSDoc** formatted docstring.

### Key Rules
- Start with a concise description of the function's purpose.
- Use `@param {type} name - Description` to document parameters.
- Use `@returns {type} Description` to document the return value.
- Use `@throws {type} Description` if the function throws any errors.

### Example

```javascript
/**
 * Calculates the estimated time of arrival (ETA) given distance and speed.
 *
 * @param {number} distance - The distance to travel in kilometers. Must be non-negative.
 * @param {number} averageSpeed - The average speed in km/h. Must be greater than zero.
 * @returns {number} The estimated travel time in hours.
 * @throws {TypeError} If either argument is not a number.
 * @throws {RangeError} If distance is negative or averageSpeed is less than or equal to zero.
 */
function calculateETA(distance, averageSpeed) {
    if (typeof distance !== 'number' || typeof averageSpeed !== 'number') {
        throw new TypeError('Arguments must be numbers.');
    }
    if (distance < 0) {
        throw new RangeError('Distance cannot be negative.');
    }
    if (averageSpeed <= 0) {
        throw new RangeError('Average speed must be greater than zero.');
    }

    return distance / averageSpeed;
}
```

## 2. Inline Comments

Inline comments are used to explain the **why** of a code block rather than the **what**. They should help developers understand the reasoning behind complex logic without cluttering the file.

### Key Rules
- **Explain the "Why", Not the "What":** Avoid commenting on obvious code behavior.
  - *Bad:* `x += 1; // Increment x by 1`
  - *Good:* `x += 1; // Compensate for 1-based indexing in third-party API`
- **Be Concise:** Keep inline comments short and to the point.
- **Placement:** Place inline comments on a new line preceding the code they describe, or as a short trailing comment on the same line if it fits easily.
- **Maintainability:** Update or remove comments when the code changes to prevent stale documentation.
- **Use sparingly:** Prefer self-documenting code (due to clear variable and function names) over adding a comment.
