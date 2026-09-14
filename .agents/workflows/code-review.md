# Code review

1. Inspect the diff: `git diff`.
2. Evaluate adherence to core constraints:
   - Minimalism & YAGNI: Is there unnecessary boilerplate or premature abstraction?
   - File safety: Are moves atomic? Are crash states journaled in SQLite?
   - Concurrency & event loop: Does any code block the GTK main loop or inotify watcher?
   - Test coverage: Are edge cases and failure modes tested?
3. Report findings categorized by severity (Critical, Warning, Suggestion).
4. Do not alter files during review unless explicitly requested.
