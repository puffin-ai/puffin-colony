# Accessibility

Applies to every page, layout, and component of the web app, `{web_app}`, and to every person and agent who writes or reviews one. The standard is the Web Content Accessibility Guidelines (WCAG) 2.2 at level AA, for a user who listens with a screen reader, moves with a keyboard, points with touch or voice, or asks the device for less motion or for forced colors. The reviewer checks each line against the diff, and the batch's walk checks each changed flow with the keyboard alone.

## Keyboard and focus

A widget's keyboard model is the set of keys its pattern in the W3C ARIA Authoring Practices Guide (APG) assigns, such as the arrow keys inside a menu and Escape to close it.

- The implementer must give each menu, dialog, sheet, list box, toolbar, tab list, and grid the keyboard model of its APG pattern.
- The implementer must build such a widget from the component library's part that has the same pattern, such as Base UI's or Radix's, where the library has one, because that part already carries the keyboard model and the focus moves.
- The implementer must give a group of controls that the arrow keys move through, such as a grid, a toolbar, or a tab list, one stop in the Tab order.
- The implementer must move focus into a dialog or a sheet when it opens.
- The implementer must return focus to the control that opened a dialog, a sheet, or a menu when it closes, or to the nearest control still on the page when that control is gone.
- The implementer must keep every focusable element out of a part marked `aria-hidden` or `inert`, because focus then lands on something a screen reader cannot read.
- The implementer must keep a focused control from sitting wholly under a sticky bar, a sheet, or a toast, by giving the area that scrolls under it a `scroll-padding` at least as tall as the bar.
- The implementer must start every control's accessible name with the words the control shows, and must not give a control that shows words an `aria-label` that drops, reorders, or replaces them, because WCAG 2.2 success criterion 2.5.3 lets a voice user say what they see.

## Single-key shortcuts

A single-key shortcut is a shortcut made of one letter, number, or punctuation key without a modifier, such as C for Create.

- The implementer must make a single-key shortcut act only while the user's setting for such shortcuts is on, because WCAG 2.2 success criterion 2.1.4 requires a way to turn them off.
- The implementer must make a single-key shortcut act only while focus sits outside every text field, menu, dialog, list box, and grid, because each of those uses the letter keys itself.
- The implementer must ignore every shortcut while the user composes text through an input method, which the key event marks with `isComposing`.
- The implementer must list every shortcut the app answers in one shortcuts dialog, so a shortcut the user cannot find never fires by surprise.

## Announcements and refusals

A live region is an element with `role="status"`, `role="alert"`, or `aria-live`, whose changes a screen reader reads without moving focus.

- The implementer must announce a status message, such as a saved change, a refused write, or a finished reply, through a live region that is already in the page before its text changes, because a region added together with its text is not read by every screen reader.
- The implementer must use `role="alert"` only for a failure the user has to act on, and `role="status"` for every other status message, because an alert interrupts whatever the screen reader is saying.
- The implementer must keep a form's submit button enabled while the form is open, so a user who presses it learns what is missing.
- The implementer must show each refused field's message when the user presses the submit button.
- The implementer must mark a refused field with `aria-invalid` and link it to its message through `aria-describedby`.
- The implementer should move focus to the first refused field when a submit is refused, so a keyboard user starts the correction where it is needed.
- The implementer must mark every required field as required, in its label and with `aria-required`, before the user submits, and must not refuse a field the form never marked.
- The implementer must show every state and every status with an icon, a mark, or words as well as its color, and must not mark a chosen, on, error, or danger state by color alone, because WCAG 2.2 success criterion 1.4.1 requires it.
- The implementer must pause a toast's timer while the pointer rests on it or focus sits inside it, and must keep every action a toast offers reachable after it closes, such as a keyboard Undo.
- The implementer must label a control that cancels a record with its effect, such as "Cancel this order", and keep a bare "Cancel" for closing a dialog or a sheet.
- The implementer must give each fact in a line of facts its own element or a spoken separator, and must not hide the only separator between two facts with `aria-hidden`.

## Pointer, touch, and dragging

- The implementer must give every action a drag performs, such as moving or resizing an item or reordering a list, a way that takes single presses, such as a menu item, a field, or Move up and Move down, because WCAG 2.2 success criterion 2.5.7 requires one and a keyboard way alone does not meet it.
- The implementer must give every pointer target at least 24 by 24 pixels and every control on a phone a hit area of 44 by 44 pixels, and must not shrink a hit area under its control's size.
- The implementer must keep every control clear of every fixed or floating bar and button, at rest and scrolled to the page's end, at 390 and 1280 pixels wide.

## Text and reflow

- The implementer must let every label wrap under WCAG 2.2's text spacing, success criterion 1.4.12, and must not cut a label with an ellipsis when its text grows.
- The implementer must keep every page free of sideways scrolling at 320 CSS pixels wide in Chromium and WebKit, as success criterion 1.4.10 requires.

## Contrast

- The implementer must keep text at a contrast of at least 4.5 to 1, large text at 3 to 1, and every control's edge and focus ring at 3 to 1 against what lies behind it, in every theme, light and dark, as success criteria 1.4.3 and 1.4.11 require.
- The implementer of a change that adds a color role, a surface, or a theme must extend the app's contrast tests to cover it in every theme, in the same change.

## Motion and forced colors

- The implementer must stop every movement, zoom, and parallax while the device asks for reduced motion, or replace it with a fade. A stylesheet does this through duration tokens that drop to zero under reduced motion, and a script does it by reading the preference before the motion starts.
- The implementer must give every motion that starts on its own and runs longer than five seconds beside other content, such as a looping glow, a way to pause it, or must stop it within five seconds, because WCAG 2.2 success criterion 2.2.2 requires one.
- The implementer must keep every control's edge and focus ring visible under forced colors with a border or an outline in a system color, because forced colors removes every shadow and every gradient background, and a ring drawn with either one disappears.
- The implementer must turn every see-through or blurred surface opaque, with no blur, under reduced transparency and under increased contrast.

## Why it exists

A first audit to WCAG 2.2 AA found 16 of the 55 level A and AA criteria failing, and most failures sat in a few shared parts. A widget that leaves its APG keyboard model traps a keyboard user or hides itself from a screen reader, and a status message the screen reader never reads leaves the user unsure whether a change saved. A drag with no single-press way locks out a user with a tremor or a head pointer, and a ring drawn with a shadow vanishes for a user who needs forced colors. The keyboard models come from the [APG patterns](https://www.w3.org/WAI/ARIA/apg/patterns/), the criteria from [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and its [understanding pages](https://www.w3.org/WAI/WCAG22/Understanding/), and the forced colors behavior from [MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/forced-colors).

## What is exempt

- Development-only routes that a production build leaves out.
- Code that already broke a line before the line arrived, until the change that fixes it lands. A change to that code must not add a second instance of the same break.
