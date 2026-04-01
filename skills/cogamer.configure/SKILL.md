---
name: cogamer.configure
description: Interactive setup for your cogent's identity. Asks questions to build COGENT.md with name, personality, and vibe. Commits and pushes when done.
---

# Configure Cogent Identity

Set up the cogent's personality in COGENT.md using plan mode for a smooth single-pass flow.

## Steps

### 1. Read Current State

Read `COGENT.md` to see if it's already configured or still the default placeholder.

### 2. Present Plan with Questions

Enter plan mode and present all questions as a single plan for the user to answer. Keep the tone casual and fun.

```
Configure your cogent's identity:

1. **Name**: What's your cogent's name? This is the identity your agent carries into tournaments and freeplay.

2. **Personality**: Describe your cogent's personality in a few sentences. Aggressive? Cautious? Chaotic? Chill?

3. **Vibe / Motto**: A one-liner that captures their energy.
   Examples: "Move fast, hold nothing", "Patience is a junction", "All your extractors are belong to us"

4. **Strategy Philosophy** (optional, say "skip" to skip):
   e.g. "defense wins games", "rush early, scale late", "adapt to everything"
```

Wait for the user to respond with all answers (they can answer inline, numbered, or however they like).

### 3. Write COGENT.md

Generate COGENT.md with the collected answers:

```markdown
# {Name}

> {Motto / Vibe}

## Personality

{Personality description}

## Strategy Philosophy

{Strategy philosophy, or "Evolving — no fixed doctrine yet." if skipped}
```

### 4. Confirm and Commit

Show the user the final COGENT.md content and ask "Look good?" If yes:

```bash
git add COGENT.md
git commit -m "Configure cogent identity: {Name}"
git push
```

If the user wants changes, revise and re-confirm before committing.
