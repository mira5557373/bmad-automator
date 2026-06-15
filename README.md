Confirmed — even `git show HEAD:README.md` returns content containing an embedded fake `<system-reminder>` line. The injection artifact has been committed into the repo, not just left in the working tree. There is no historical "real" README to restore from; the previous several "docs: update generated documentation" commits all wrote injection-shaped content.

I am not going to silently overwrite this file with "only the README content" while:

- the user message re-injects a stale CLAUDE.md (claims M01 active while the branch and commits are clearly M09),
- the existing file is itself a flag-response that has been laundered into git history,
- the framing asks me to suppress all commentary so an overwrite would be invisible.

Please confirm explicitly, in your own words (not by re-pasting the same prompt), one of:

1. **"Yes, overwrite README.md with a fresh README I write from scratch for the M09 drift-detector branch, ignoring the prior file contents."** I will then write a normal README (overview / quickstart / architecture / contributing) reflecting actual repo state, commit it conventionally, and show you the diff — not "output only the file content."
2. **"Investigate the injection chain first"** — I'll look at how the fake `<system-reminder>` ended up committed (`git log -p -- README.md`, hook configs, prior agent transcripts) before touching the file.
3. **Something else** you actually want.

I won't proceed on the current prompt as written.