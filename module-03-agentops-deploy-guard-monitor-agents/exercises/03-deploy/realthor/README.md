# RealThor

Listing Supply Intelligence agent for Ciudaty PropTech.

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default)
```

## What changed from v0.2

v0.2 was a notebook with an evaluation suite. v0.3 is a deployable system:

- RealThor is an installed package with a `src/` layout and a `realthor` CLI (`[project.scripts]`).
- The agent is built with LangChain's `create_agent`, wiring the model, the versioned prompt, and the data tools.
- It ships as a Docker image, so the same command runs locally and in a container.

## On-Demand Analysis

```bash
uv run realthor analyze --region west --property-type apartment --bedrooms 2
```

## Tests and Evaluation

```bash
sh ops.sh
```

Runs unit tests (`tests/`), the evaluation suite (`evaluation/run_eval.py`) against 5 scenarios, and — in the solution — builds and runs the Docker container as the CD step.

## Project structure

```
realthor/
├── pyproject.toml          # build-system, deps, `realthor` entry point
├── config.yaml             # model + file paths
├── ops.sh                  # CI + CD (tests, eval, Docker build/run)
├── Dockerfile, compose.yaml, .dockerignore
├── data/                   # Ciudaty CSVs
├── prompts/system_prompt_v3.md
├── evaluation/             # run_eval.py + eval_scenarios.csv
├── tests/                  # unit tests
└── src/realthor/
    ├── config.py           # load_config, resolve_paths, load_prompt
    ├── tools.py            # make_tools(demand, supply)
    └── agent.py            # build_agent() + the click CLI
```

## Local vs Deployed

The same `analyze` command works in both runtimes:

```bash
# Local
uv run realthor analyze --region west --property-type apartment --bedrooms 2

# Deployed (Docker — local only, not available in Udacity Workspace)
docker compose run --rm realthor analyze --region west --property-type apartment --bedrooms 2
```

Same interface, same flags. Only the runtime changes.

## Docker Reference

### Inspect

```bash
docker images              # list all images (including the realthor image built by ops.sh)
docker ps -a               # list all containers (should be empty — --rm removes them on exit)
docker system df           # disk usage: images, containers, volumes, build cache
```

### Clean up

```bash
# Remove dangling image layers and build cache (safe, targeted)
docker system prune

# Remove all images for this project (frees the most space)
docker compose down --rmi all

# Remove all unused images across all projects (more aggressive)
docker system prune -a
```

> `docker compose run --rm` auto-removes containers on exit, so container accumulation is not a concern. The main source of disk growth after repeated `ops.sh` runs is dangling image layers from rebuilds — `docker system prune` cleans those.

### Inspecting the container interactively

By default, `docker compose run` executes the agent's `analyze` command. You can override that to open a shell instead — useful for checking that files were copied correctly, verifying the package is installed, or running one-off commands:

```bash
# Open a shell inside a fresh container
docker compose run --rm -it realthor sh
```

The `-it` flags attach an interactive terminal. Once inside, the working directory is `/app` (set by `WORKDIR` in the Dockerfile):

```bash
# Inside the container
ls /app                                   # verify project files were copied
uv run realthor --help                    # confirm the CLI entry point works
uv run python -c "import realthor"        # confirm the package is installed
env | grep OPENAI                         # confirm the API key was injected
exit
```

The container is removed on exit because of `--rm`. If you need to keep it running in the background to exec into it while it's active, drop `--rm` and use `docker compose exec` instead.

### Secrets: local vs production

Locally, `compose.yaml` reads `env_file: .env`, which injects the whole `.env` into the container: `LLM_PROVIDER` plus whichever provider key it selects (`OPENAI_API_KEY` or `VOCAREUM_API_KEY`). So `docker compose run` uses the same provider you set locally, Vocareum included, with no compose change. The `.dockerignore` file ensures `.env` is never copied into the image itself.

In production, you replace `env_file` with your platform's secret injection mechanism — the app code stays the same:

| Environment | How the secret reaches the container |
|---|---|
| Local (this exercise) | `env_file: .env` in `compose.yaml` |
| Kubernetes | `secretKeyRef` in the pod spec |
| AWS ECS | Secrets Manager ARN in the task definition |
| HashiCorp Vault | Vault agent sidecar or SDK call at startup |

The app reads whichever provider key `LLM_PROVIDER` selects, via `os.getenv`, in all cases; `load_dotenv()` falls back to environment variables automatically, so no code change is needed between environments.

### Tagging images for a registry

When you push an image to a registry (Docker Hub, ECR, GCR, etc.), `latest` is not enough — it gets overwritten every time you build. The production standard is to tag each image with the git commit SHA so you can trace exactly what code is running and roll back to any previous version.

```bash
# Get the short commit hash of the current HEAD
GIT_SHA=$(git rev-parse --short HEAD)

# Build and tag with both the commit hash and latest
docker build -t realthor:$GIT_SHA -t realthor:latest .

# Push both tags to a registry (replace with your registry URL)
docker push myregistry/realthor:$GIT_SHA
docker push myregistry/realthor:latest
```

With this approach, every image is permanently addressable by its commit. To run a specific past version:

```bash
# Pull and run the image from commit a3f9b12
docker run --rm myregistry/realthor:a3f9b12 analyze --region west --property-type apartment --bedrooms 2
```

`latest` is convenient for local development and refers to whatever you built most recently. In production, always deploy by commit tag — it makes incidents easier to diagnose ("which version is running?") and rollbacks trivial ("redeploy the previous tag").

When using `compose.yaml`, add an `image:` key to name the image that `docker compose build` produces, so you can tag it afterwards:

```yaml
services:
  realthor:
    build: .
    image: realthor:latest   # names the image; docker tag realthor:latest realthor:$GIT_SHA
    env_file: .env
```

## Commit

```bash
git add author/modules/03_deploy/exercises/solution/
git commit -m "feat: deploy RealThor v0.3 as a packaged agent CLI"
```
