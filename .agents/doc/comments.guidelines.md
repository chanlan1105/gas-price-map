---
name: 'Code Commenting Guidelines'
description: 'Instructions for commenting code in this repository'
---

This document outlines the rules and standards for commenting code in this repository. All code contributions must adhere to these guidelines to ensure consistency, readability, and maintainability.

## 1. Python Methods & Functions (NumpyDoc)

Every Python method, function, and class must include a **NumpyDoc** formatted docstring. Do not use standard Sphinx or Google style docstrings.

### Key Rules
- Start with a concise, single-line summary in the third person (e.g., "Calculates the distance...").
- Document inputs under the **Parameters** section.
- Document outputs under the **Returns** or **Yields** section.
- Document exceptions under the **Raises** section.

### Example

```python
def calculate_fuel_efficiency(distance: float, fuel_consumed: float) -> float:
    """Calculates the fuel efficiency of a vehicle in miles per gallon.

    Parameters
    ----------
    distance : float
        The total distance traveled in miles. Must be non-negative.
    fuel_consumed : float
        The amount of fuel consumed in gallons. Must be greater than zero.

    Returns
    -------
    float
        The calculated fuel efficiency in miles per gallon (mpg).

    Raises
    ------
    ValueError
        If `distance` is negative or `fuel_consumed` is less than or equal to zero.
    """
    if distance < 0:
        raise ValueError("Distance cannot be negative.")
    if fuel_consumed <= 0:
        raise ValueError("Fuel consumed must be greater than zero.")
        
    return distance / fuel_consumed
```

## 2. JavaScript / TypeScript Methods & Functions (JSDoc)

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

## 3. Inline Comments

Inline comments are used to explain the **why** of a code block rather than the **what**. They should help developers understand the reasoning behind complex logic without cluttering the file.

### Key Rules
- **Explain the "Why", Not the "What":** Avoid commenting on obvious code behavior.
  - *Bad:* `x += 1 # Increment x by 1`
  - *Good:* `x += 1 # Compensate for 1-based indexing in third-party API`
- **Be Concise:** Keep inline comments short and to the point.
- **Placement:** Place inline comments on a new line preceding the code they describe, or as a short trailing comment on the same line if it fits easily.
- **Maintainability:** Update or remove comments when the code changes to prevent stale documentation.
- **Use sparingly:** Prefer self-documenting code (due to clear variable and function names) over adding a comment.
