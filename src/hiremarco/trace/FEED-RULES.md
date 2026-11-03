# Marco Live — feed rules for the hireMarco team

The banner (`Marco Live.html`, 1920×312) shows only what the event feed sends. These rules keep it readable on a TV and true to Marco's voice.

## 1. Sending events
- `window.marco.push([events])`, newest last. One event per happening.
- Also: `marco.replay(true|false)`, `marco.detail(true)` (raw event panel), `marco.scale(u)`, `marco.layout('banner'|'full')`, `marco.reset()`.
- Timestamps: `ts` in ms or ISO. Clocks and animations are anchored to `ts`, so send the real time of the event.
- A model call = two events with the same `call_id`: start (`type:"call_start"`, `model`, `task`) and finish (`type:"call_end"`, `status`, `summary`, `detail`, `latency_ms`, `request_id`, `metrics`). Same id updates the line in place; it never adds a second.

## 2. Fields the screen reads
- `plain` — the one big sentence (what is happening now). Required whenever the situation changes.
- `stages` (array) + `stage` — the path. A new `stages` array starts a new task (no "stepped back" flagged). A lower `stage` within a task is shown as a correction.
- `model` — one of the six Meta model names. Match the spelling.
- `task` — what the model is being asked, present tense.
- `status` — `running` / `ok` / `held` / `error` (or `timeout`). Held = amber, error = red, ok = green.
- `summary` — the decision in one line. `detail` — why, one or two lines.
- `latency_ms`, `request_id`, `metrics` (object, ≤2 keys shown) — the receipt. Only real numbers.
- `thought` — Marco thinking (grey, unresolved). `type:"learned"` or `learned:true` — something kept in memory (yellow).
- `type:"tool_skipped"` / `"left_out"` — a tool deliberately not used (amber catch).
- Messages: `type:"message_sent"`, `via:"WhatsApp"`, `text` — Marco's text (green bubble, timed ticks). Incoming texts from Felix are NOT shown (they're on camera).
- Email: `type:"email_received"`, `via:"Gmail"`, `from`, `subject`, `text` — the only incoming item shown ("noticed", white card, held 9 s).
- `motif` (optional) — pick the mark: `vu eq wave knob fader rec bars` (studio) · `swatch hanger gtag button tape stitch` (wardrobe) · `clock plate cal` (dinner). If omitted it's inferred from model + words. Marks never repeat on screen or within the last four; SAM tags, Gmail, WhatsApp and the look board are exempt.
- `motif:"phone"` or the word "call" in `task` → the word **calling** with the ringing signal. Everything else says **using**.

## 3. Character budgets (hard limits for a clean screen)
The page shrinks type one step before truncating; beyond these it adds an ellipsis.
- `plain` (Now sentence): **≤ 60 chars** ideal, 90 max.
- `task` / `summary` / `thought` / `learned`: **≤ 80 chars** ideal, 120 max. Two short sentences beat one long one.
- `detail`: ≤ 110 chars (shown only in the square layout).
- WhatsApp `text`: ≤ 90 chars.
- Email `subject`: ≤ 40 chars. Email body: first 2 lines show when alone, hidden when sharing the column.
- `request_id`: any length (shortened to `req 3c9a…b0d4`). `metrics`: short keys, ≤ 2 shown.

## 4. Inline marks in text
- `~~words~~` — Marco crosses them out, drawn ~1 s after the line lands. Use for a self-correction.
- `==words==` — yellow highlighter sweep. Use only for something Marco **learns / keeps**.
- One mark per sentence. Never both on the same phrase.

## 5. Marco's voice (what reads well at 1920 wide, from across a room)
- Short declaratives. Fragments allowed. "Held. The chorus clips at the limiter."
- Sentence case, a period at the end of `plain`. No exclamation marks, no emoji, no hedging.
- Third person for Marco in `plain` ("Marco is printing the master."); first person in texts and thoughts ("I'll handle the table.").
- Numbers specific and mono-friendly: "−14.2 LUFS", "+41k", "8:30".
- A failure says failure: `status:"error"` with a plain `summary` ("The transcription call timed out."). Don't soften it — catching it is the best moment.

## 6. Pacing
- Leave ≥ 1.5 s between events so the entrance (380 ms) and type-on finish. Two events can land at once if they truly happened at once.
- After a `held` or `error`, send the next `stage`/`plain` within a few seconds so the correction is visible.
- The screen shows two lines; a new one replaces the older. Running calls and a just-noticed email are protected from replacement.

## 7. Before the final build
- Delete the `<script id="marco-sample">` block (or set `MARCO_SAMPLE=false`).
- Embed Inter Tight + JetBrains Mono as `@font-face` data URLs; embed `gmail.webp`. No network calls.
