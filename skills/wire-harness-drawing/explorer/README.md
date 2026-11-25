# Embedding the harness explorer

You are giving a harness an interactive view: a 3D view and a 2D view built from the drawing, where clicking a connector shows its pinout and clicking a wire shows its row and where each end lands. It is one custom element, `<wire-harness-explorer>`, in one ES module with no dependencies and no I/O. Every number it shows comes from the harness model the generator writes.

## Rules

- The model is `<name>.harness.json`, written by `scripts/harnessgen.py` beside the drawing. Never edit it or write one by hand; change `harness.yaml` and regenerate.
- The component is `explorer/wire-harness-explorer.js` in this skill. A project holds exactly one copy of it, however many harnesses it shows.
- Write no other view, wrapper or converter for the harness. The surrounding page carries words, not drawings.
- Never type a number into the surrounding page that the model does not hold. Quote lengths, part numbers and counts from the model or the drawing package.

## Procedure

1. **Generate** the package for each harness. Fix every ERROR first; an explorer of a harness that fails its checks says nothing reliable, and it shows NOT FOR RELEASE with the error count, as the sheets do.
2. **Place the component once.** Search the project for `wire-harness-explorer.js`.
   - None: copy the skill's file into the project's static assets (for example `assets/`, `public/` or `static/`).
   - One: compare the version on its first line with the skill's copy. Replace it when the skill's is newer.
   - Never leave two copies.
3. **Place each model** beside the page that shows it, or inline it (step 4).
4. **Embed.** Load the module once per page, then add one element per harness.
   - Static HTML, Markdown or MDX: put the model inline, as the text of a child script element with type `application/json`, inside the element. Load the module with a module script tag whose `src` is the component's path.
   - Framework code (React, Vue, Svelte, Angular): import the module once for its side effect, render the element, and set its `harness` property to the parsed model. `view` works as a property or an attribute, so React 19 can pass it as a prop.
   - Attributes: `view="2d"` to open on the 2D view (default 3D); `theme="light"` or `theme="dark"` to match a site's own toggle (default: the reader's system setting).
   - Any number of explorers may share a page: they draw their 3D views with one WebGL context between them, made when the first 3D view shows and released when the last explorer leaves the page.
5. **Frame it.** Above the element, write in this order:
   1. an eyebrow line: `<drawing number> · <key spec> · rev <rev>`;
   2. a title that states what the reader should take away;
   3. a one- or two-sentence lede that says how to read it (click a connector or wire; what the 2D and 3D views are).

   Below it, write a caption that says what the reader is looking at, with the key numbers in bold, and whether the geometry is schematic (the drawing's layout laid flat, not to scale) or routed (the specified route, wires and bodies at nominal size). The component states the same in its own footer.
6. **State what is unknown.** End with one short note that lists every length shown as TBD or ≥, every generic connector, and every wire whose colour is not chosen, as still to be decided. Tag them as placeholders, not as facts.
7. **Check before delivering.** Open the page and confirm:
   - the 3D view opens framed on the whole harness;
   - clicking a connector shows its pin table, and its pinout when the source states a face;
   - clicking a wire shows its row and a popover at each end;
   - the 2D view shows every wire in its colour along each bundle, names each breakout, gives each connector its label, and shows the heat-shrink labels where sheet 1 puts them;
   - dark mode and phone width both work.
8. **Report** the placeholders from step 6 in your reply: they are what the harness still needs decided or measured.

## Writing

- Write as an expert to an expert new to this harness. Use terse, mechanism-level sentences.
- Use the drawing's units, with a space before the unit (`300 mm`), the true minus sign and `±`, `Ø` and `×`.
- Write "not stated" or "TBD" in italics for missing values; never leave them blank.
- No marketing tone and no filler.

## What the component does on its own

- Follows the reader's light or dark setting, or the `theme` attribute.
- Asks for IBM Plex Sans and Plex Mono with system fallbacks and loads no fonts itself. If the page wants Plex, the page loads it.
- Fits phone width; the stage is at most 62 % of the viewport height. 2D text keeps one size on screen however the drawing is scaled or zoomed.
- Pins, wires and connectors carry text labels and the views carry `role="img"` labels for screen readers.
