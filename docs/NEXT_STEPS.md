# What is left (deadline Fri 27 Nov, 12:00 noon)

Groq free tier: 200k tokens per day **per model**, rolling. One demo run uses ~100-150k. If a run dies with
"tokens per day", wait or switch models in `.env`.

1. When quota is back, re-run demo 2 on the fixed code (optional but removes the caveat in its NOTE.md):
   `forge run demos/spares_docs --brief "@demos/briefs/spares.txt" --out runs/demo2_spares --cases 24`
2. Third unseen brief (robustness, not yet run):
   `forge run demos/port_docs --brief "@demos/briefs/port.txt" --out runs/demo3_port --cases 20`
   Check that it picks the `weather` tool and nothing unnecessary.
3. Record the video using `docs/DEMO_SCRIPT.md` (do this AFTER step 1 so the numbers match; update README table too).
4. Create an empty GitHub repo, then: `git remote add origin <url>` and `git push -u origin main`.
5. Optional hosted link: any host that can run `uvicorn forgeai.server:app` with Node used only to build `web/`
   (e.g. a Docker Space). Add authentication or disable /api/build and chat limits before making it public.

`.env` holds the Groq key and is git-ignored. Never commit it.
