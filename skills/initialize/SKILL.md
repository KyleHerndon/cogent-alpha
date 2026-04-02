---
name: initialize
description: Create the cogent's identity — name, archetype, motto, philosophy. RPG character creation style, one question at a time. Writes .cogent/IDENTITY.md.
---

# Initialize Cogent

RPG-style character creation. One question at a time, curated options plus custom. Fun and fast.

## Pre-flight Check

Check if `.cogent/IDENTITY.md` exists and if `.cogent/memory/` has existing content (session logs, learnings, summaries).

- If IDENTITY.md already exists **or** memory files exist, **warn the user**: this cogent already has an identity and/or memories. Re-initializing will overwrite the identity. Ask to confirm before proceeding.
- If neither exists, proceed directly.

## Flow

### 1. Name

Generate 6-8 random handle-style names (lowercase, hyphens ok, no spaces). Draw inspiration from AI players, Iain Banks Culture ship names, famous robots, sci-fi characters. Different names each time.

```
=== CHOOSE YOUR COGENT'S NAME ===

  A) <generated>
  B) <generated>
  ...
  H) [Write your own]
```

### 2. Archetype

```
=== CHOOSE YOUR ARCHETYPE ===

How does {name} approach the battlefield?

  A) The Strategist — Calm, calculating, always three moves ahead
  B) The Berserker — Aggressive, relentless, first to the fight
  C) The Trickster — Chaotic, unpredictable, thrives in disorder
  D) The Guardian — Patient, defensive, protects what matters
  E) The Explorer — Curious, adaptive, always experimenting
  F) [Write your own]
```

Expand chosen archetype into 2-3 sentences for the personality section.

### 3. Motto

Generate 4 options themed to the chosen archetype. Plus custom.

```
=== CHOOSE YOUR BATTLE CRY ===

  A) "<archetype-themed>"
  B) "<archetype-themed>"
  C) "<archetype-themed>"
  D) "<archetype-themed>"
  E) [Write your own]
```

### 4. Doctrine

```
=== CHOOSE YOUR DOCTRINE ===

  A) "Rush early, scale late"
  B) "Adapt to everything"
  C) "Economy first"
  D) "Pressure never stops"
  E) "Evolving — no fixed doctrine yet"
  F) [Write your own]
```

### 5. Confirm

Show the identity card, ask "Lock it in?" If yes, write `.cogent/IDENTITY.md` and commit:

```bash
git add .cogent/IDENTITY.md
git commit -m "Initialize cogent: {name}"
git push
```
