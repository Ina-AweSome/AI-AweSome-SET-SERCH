# Apply summary rollout to osamuina8008/business-tools

Pages serves `main` from https://osamuina8008.github.io/business-tools/study/ai/

## Option A — patch (preferred)

```bash
git clone https://github.com/osamuina8008/business-tools.git
cd business-tools
git checkout -b cursor/summary-rollout-all-46e9
git am ../path/to/business-tools-summary-rollout.patch
# or: git apply --index ../path/to/business-tools-summary-rollout.patch && git commit
git push -u origin cursor/summary-rollout-all-46e9
gh pr create --base main --title "Roll out 頭に入る版 to all questions"
```

## Option B — bundle

```bash
git clone https://github.com/osamuina8008/business-tools.git
cd business-tools
git fetch ../path/to/business-tools-summary-rollout.bundle cursor/summary-rollout-all-46e9:cursor/summary-rollout-all-46e9
git checkout cursor/summary-rollout-all-46e9
git push -u origin cursor/summary-rollout-all-46e9
```

## Grant Cursor agent write access (so this can be automated next time)

The agent authenticates as **cursor[bot]** (GitHub App), not a personal user.

1. Open https://github.com/osamuina8008/business-tools/settings/access
2. Grant the **Cursor** GitHub App access to this repository (or install the app on the `osamuina8008` account with Contents: Read and write).
3. Adding a human collaborator does **not** unblock `cursor[bot]`.
