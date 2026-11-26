# Hosting ForgeAI (free tier)

The repository contains a `Dockerfile` and a Render blueprint (`render.yaml`). The image builds the Vite frontend,
then serves it together with the API from one Python process.

A deployment of this blueprint runs at https://forgeai-lc5t.onrender.com.

## Render
1. Push the repository to GitHub.
2. On https://render.com choose **New > Blueprint** and select the repository.
3. When asked, enter the two secrets:
   - `FORGE_LLM_API_KEY`: a Groq key (create a separate one for hosting, so it can be revoked on its own).
   - `FORGE_ACCESS_CODE`: a long random phrase. Without it, building new agents stays disabled.
4. Deploy. The first build takes several minutes. Free services sleep when idle, so the first visit can be slow.

## What a visitor can do
| Action | Without the access code | With it |
|---|---|---|
| Browse the demo runs, exams, reports | yes | yes |
| Chat with the demo agents | yes (10 per minute per visitor, 300 per day in total) | yes |
| Forge a new agent, approve requirements | no | yes |

## Limits to know about
- Agents built on the hosted site are lost on restart (free disks are temporary). Demo runs are part of the image.
- The hosted image uses the built-in TF-IDF embedder to stay within free memory, so retrieval is weaker than with
  the sentence-transformers model used locally.
- All visitors share one model quota.
- The limits are in memory and per process. This is a demo, not a multi-user product: there are no user accounts.

## Run the same thing locally
```
docker build -t forgeai .
docker run -p 7860:7860 -e FORGE_LLM_BASE_URL=https://api.groq.com/openai/v1 -e FORGE_LLM_API_KEY=... -e FORGE_ACCESS_CODE=... forgeai
```
