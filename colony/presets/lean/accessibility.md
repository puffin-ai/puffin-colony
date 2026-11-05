# Accessibility

Applies to every change a person sees or touches.

## Must

- Use the native element for the job: a button for an action, a link for navigation, a label for each field, a heading for each section.
- Make every action work with the keyboard alone, in a sensible order, with a visible focus ring.
- Give every image a text alternative, or mark it as decoration.
- Give every icon-only control a name a screen reader says.
- Keep text contrast at 4.5:1 or more, and 3:1 for large text and for controls, in light and dark.
- Make touch targets at least 44 by 44 points, with space between them.
- Show errors next to the field they belong to, in words, not by color alone.
- Move focus into a dialog when it opens, keep it there, and return it when the dialog closes.
- Respect the person's settings: reduced motion, larger text, and light or dark.
- Check each changed screen at phone width, 390×844, and at desktop width.

## Must not

- Use color, position or shape alone to carry meaning.
- Remove a focus outline without a visible replacement.
- Put a click handler on an element that isn't a control, or nest one control inside another.
- Disable zoom, or fix text in a size that doesn't grow with the person's setting.
- Start motion, sound or a timer the person can't pause or stop.
