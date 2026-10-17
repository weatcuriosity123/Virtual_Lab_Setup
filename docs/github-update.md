# Publish this update to GitHub

This bundle contains source and documentation only. It does not contain `.env`, session databases, tunnel credentials, student image layers or live desktop routes. Publishing it does not change the running Pi service.

Use a fresh clone on your Pi or computer rather than copying the live backend with its private data. If you downloaded `virtual-lab-main-update.tar.gz` and copied it to your Pi home directory:

```bash
cd ~
git clone https://github.com/weatcuriosity123/Virtual_Lab_Setup.git virtual-lab-github-update
cd virtual-lab-github-update
git switch main
git pull --ff-only origin main
tar -xzf ~/virtual-lab-main-update.tar.gz --strip-components=1 -C .
git status --short
git add README.md .gitignore .github backend cloudflare docs scripts student-image tests
git diff --cached --stat
git diff --cached --check
git commit -m "feat: publish multi-session Linux lab with Pi and EC2 deployment guides"
git push origin main
```

If Git asks for author identity, configure your own name and GitHub-associated email for this clone, then retry the commit. Use your existing GitHub authentication setup, an SSH remote, or GitHub CLI authentication. Never put a token into a command or paste it into chat. GitHub account passwords do not authenticate HTTPS Git pushes.

If the repository requires a pull request, keep the commit, create a branch and publish it instead:

```bash
git switch -c feature/current-linux-lab
git push -u origin feature/current-linux-lab
```

Open a pull request targeting `main`. Suggested description: "Adds the current FastAPI session manager, browser lab portal, startup and inactivity handling, deployment configuration, Pi/EC2 guides and mocked lifecycle checks. Preserves the working code and documents the missing original student-image build recipe."

If the push is rejected because main changed, fetch and review the new commits before rebasing/merging. Do not force-push. Earlier experiment branches do not need deletion or merging just to publish these files.
