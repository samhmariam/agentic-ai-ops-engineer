# Module 19 - CI/CD Pipeline with GitHub Actions

## Overview

In this exercise you will build a full CI/CD pipeline using GitHub Actions that runs on every push to `main`. The pipeline runs code quality checks, builds and pushes a Docker image to ECR, and deploys the updated image to ECS.

---

## Prerequisites

- The ECS cluster and service must be running (`beans-api-cluster` / `beans-api-service`)
- Your ECR repository (`beans-api`) must exist
- GitHub secrets must be set. Use the GitHub CLI to add them:

```bash
gh secret set AWS_ACCESS_KEY_ID     --body "<value>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<value>"
gh secret set AWS_SESSION_TOKEN     --body "<value>"
gh secret set AWS_REGION            --body "us-east-1"
gh secret set ECR_REGISTRY          --body "<account_id>.dkr.ecr.us-east-1.amazonaws.com"
```

## 1. Complete `ci.yml`

Complete the TODOs in `ci.yml`, then place it in `.github/workflows/` at the root of your repository. The pipeline has four jobs that run in order:

**`lint`**: install `ruff` and run it against `main.py` and `quality_check.py`.

**`quality-check`**: run `quality_check.py`. The pipeline fails if the script exits with code 1.

**`build`**: build the Docker image tagged with the first 8 characters of the commit SHA plus a timestamp, push it, then tag and push as `:latest`.

**`deploy`** (needs: build): download the current ECS task definition, render it with the new `:latest` image using, and deploy it.

Read more about AWS actions for GitHub: https://github.com/aws-actions

---

## 2. Push and verify the pipeline

Commit and push to `main` to trigger the workflow:

```bash
git add .github/workflows/ci.yml
git commit -m "add CI/CD pipeline"
git push origin main
```

Navigate to your repository on GitHub under **Actions** to monitor each job. A successful run will deploy the updated image to your ECS service automatically.
