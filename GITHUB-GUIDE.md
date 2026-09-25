# How to use this repository

This repo is the official starting point for **05 · Recovery Manager**.

Round 2 is an **individual build**, and each participant works in their **own GitHub fork**.

The workflow is:

```text id="a9p4sg"
Official Repository
        ↓
      Fork
        ↓
 Your GitHub Fork
        ↓
 Build + Test
        ↓
 Commit + Push
        ↓
 Final Submission
```

**New here? Read these first:**

1. [`README.md`](README.md) explains the Recovery Manager problem, data and build expectations.
2. [`RULES.md`](RULES.md) covers the repository and engineering rules.

---

## 0. One-time setup

You need `git` installed and a GitHub account.

Set your identity once, if you haven't before:

```sh id="y3b1xg"
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"   # use the email on your GitHub account
```

If you use SSH, check it works with `ssh -T git@github.com`. It should greet you by username. If you'd rather use HTTPS, the easiest way to sign in is the GitHub CLI:

```sh id="o9a2f4"
gh auth login
```

## 1. Fork and clone the repo

First, fork the official repository into your own GitHub account:

```text id="1b1x2m"
https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager
```

Then clone **your fork**.

### SSH

```sh id="58j3qx"
git clone git@github.com:<your-github-username>/cube-05-recovery-manager.git
cd cube-05-recovery-manager
```

### HTTPS

```sh id="p7v5cd"
git clone https://github.com/<your-github-username>/cube-05-recovery-manager.git
cd cube-05-recovery-manager
```

Replace `<your-github-username>` with your GitHub username.

## 2. Start building

You do **not** need to create a participant branch or participant folder in the organiser repository.

Build your Recovery Manager directly inside your own fork.

You may use `main` or create your own development branches inside your fork.

For example:

```sh id="h7v2kr"
git checkout -b feature/recovery-reasoning
```

A simple development flow is:

```text id="j3r8na"
Understand
    ↓
Build
    ↓
Test
    ↓
Evaluate
    ↓
Document
    ↓
Demo / Deploy
    ↓
Submit
```

See [`README.md`](README.md) for the Recovery Manager requirements.

## 3. Organise your project

You are free to choose your own project structure.

For example:

```text id="k0t6eu"
cube-05-recovery-manager/
├── data/
├── src/
├── tests/
├── README.md
├── RULES.md
├── GITHUB-GUIDE.md
├── ARCHITECTURE.md
└── ...
```

This is only an example. Your final repository should be clear and easy to run.

You do not need to create:

```text id="p1y6rv"
submissions/<your-github-username>/
```

in the organiser repository.

## 4. Commit and push, often

Commit your development work regularly.

```sh id="a3w8zd"
git status
git add .
git commit -m "Implement recovery reasoning"
git push origin main
```

If you are working on your own branch:

```sh id="n9v4qa"
git push -u origin feature/recovery-reasoning
```

After the first push, `git push` is enough when your upstream branch is configured.

Use meaningful commit messages, for example:

```text id="x2n6pw"
Implement fee report parsing
Add charge-to-unit matching
Add evidence reasoning
Add claim decision logic
Add uncertainty handling
Add evaluation metrics
```

Avoid unclear messages such as:

```text id="c5v7ly"
update
changes
final
final2
fix
```

### Build-phase commit rule

All code commits forming your Round 2 submission must be made during the **authorised build phase**.

Round 2 build begins:

**25 September 2026 · 9:00 AM IST**

Once the build phase ends, do not continue making Round 2 code changes.

## 5. No pull request is required

Your Round 2 work does **not** need to be submitted through a pull request to the organiser repository.

There is no requirement to:

* open a PR into the organiser's `main`,
* wait for an organiser merge,
* create a username branch in the organiser repository,
* or use `submissions/<your-github-username>/`.

Your own fork is your development and submission repository.

## 6. What happens next

When you are ready to submit, use the official Cube Buildathon submission form.

### Important dates

* **Build begins:** 25 September 2026 · 9:00 AM IST
* **Submissions open:** 27 September 2026
* **Final submission deadline:** 1 October 2026 · 6:00 PM IST

The submission form closes permanently at the final deadline.

**There is no reopening and no resubmission.**

Before submitting, verify that your repository, documentation, evaluation results, demo and required links are final.

## 7. Asking for help, or reporting a problem

* **Something in the shared data or docs is wrong or contradicts itself:** raise it with the organisers and identify it as a `finding`. Do not silently modify the official repository.
* **Access or permission problems:** make sure you are signed in to the GitHub account that owns your fork, or contact an organiser.
* **Cross-manager integration questions:** use the official Buildathon communication channels and evidence-contract guidance provided by the organisers.

## Common problems

| Symptom                         | Fix                                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------- |
| `remote: Repository not found`  | Make sure you cloned **your own fork** and the repository URL is correct.                         |
| `remote: Permission denied`     | Check that you are authenticated to the GitHub account that owns your fork.                       |
| `rejected ... (fetch first)`    | Run `git pull --rebase`, resolve any conflicts, then `git push`.                                  |
| Push rejected                   | Make sure you are pushing to your own fork and the correct branch.                                |
| Merge conflict                  | Open the affected file, resolve the conflict, then `git add` and `git commit`.                    |
| Environment not working         | Check the README setup instructions, dependencies and environment variables.                      |
| Model/API failure               | Preserve the available information and move the case into an appropriate pending/review state.    |
| Missing evidence                | Do not invent evidence. Use an appropriate `UNCERTAIN` or review outcome.                         |
| Accidentally committed a secret | **Revoke the credential immediately**, then remove it from the repository history as appropriate. |

## Never commit secrets

Never commit:

* API keys,
* `.env` files containing secrets,
* passwords,
* access tokens,
* private credentials.

Use environment variables instead.

If you do push a key by accident, **revoke the key immediately**. Deleting the commit alone does not make an exposed credential safe.

## Commands you'll use every day

```sh id="m8q3sv"
git status                              # what changed
git add .                              # stage changes
git commit -m "..."                    # commit changes
git push                               # send to your fork
git pull --rebase                      # update your local branch
git log --oneline -10                  # recent history
```

If you use your own development branch:

```sh id="f4z8kn"
git checkout -b feature/my-change
git push -u origin feature/my-change
```

## Before you submit

```text id="g8w6pe"
[ ] Working Recovery Manager
[ ] Working in my own GitHub fork
[ ] Required code commits completed during the authorised build phase
[ ] README.md complete
[ ] RULES.md reviewed
[ ] ARCHITECTURE.md complete
[ ] Evaluation completed
[ ] Claim precision / relevant metrics documented
[ ] Failure modes documented
[ ] Demo ready
[ ] Deployment URL verified, if applicable
[ ] LinkedIn post published
[ ] CodeQuesters tagged
[ ] Sydon.AI tagged
[ ] Submission links verified
[ ] Final submission ready before 1 October 2026 · 6:00 PM IST
```

**Cube Buildathon · 05 · Recovery Manager**
