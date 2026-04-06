# Externalize Protocol

> Triggered when the user says "externalize" or "externalize your thoughts."
> This is a STANDALONE action. Do NOT wrap up unless separately asked.

## Steps

1. **Determine session number** — check the Session Log in CLAUDE.md for the
   latest session number, increment by 1

2. **Pull wiki** — ensure `docs/wiki/` is current:
   ```bash
   git -C docs/wiki pull   # or clone if missing
   ```

3. **Create session wiki page** — write `docs/wiki/Session{N}.md` with:
   - Date, focus, duration estimate
   - What was done (with detail — reference actual files and commits)
   - Discoveries and observations
   - Decisions made and why
   - Raw Thinking — observations, concerns, trade-offs, and loose threads that
     came up during the session but weren't part of the main deliverable.
     Things you'd mention if pair programming: prerequisites noticed, corners
     being painted into, intent mismatches, unresolved questions.
   - What's next

4. **Update SessionRetrospectives.md** — read the current index, add the new
   session row, write it back

5. **Commit and push wiki:**
   ```bash
   cd docs/wiki
   git add -A
   git commit -m "retro: Session {N} — <one-line summary>"
   git push
   ```
