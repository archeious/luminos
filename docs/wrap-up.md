# Session Wrap-Up Checklist

> Triggered when the user says "wrap up", "end session", or similar.
> Always externalize FIRST, then do the steps below.

## Steps

1. **Externalize** — run the `docs/externalize.md` protocol if not already
   done this session

2. **Reread CLAUDE.md** — ensure you have the latest context before editing

3. **Update CLAUDE.md:**
   - Update **Current Project State** — phase, last worked on (today's date),
     last commit, blocking issues
   - Update **Session Log** — add new entry, keep only last 3 sessions,
     remove older ones (full history is in the wiki)

4. **Commit and push main repo:**
   ```bash
   git add CLAUDE.md
   git commit -m "chore: update CLAUDE.md for session {N}"
   git push
   ```

5. **Verify nothing is unpushed** — both the main repo and docs/wiki should
   have no pending commits

6. **Recommend next session** — tell the user what the best next session
   should tackle, in priority order based on PLAN.md and any open Forgejo
   issues
