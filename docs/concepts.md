# Concepts: Task, Project, Agent

Xylocopa is built around three objects. A common new-user question is "where do I start, should I create projects first? Agents first? Tasks first?" The answer is **tasks first**, and this page explains why.

## Task

A **task** is a unit of work you want done, "add a contact form", "fix the mobile footer". A task can be retried, refined, or postponed; it outlives any single agent attempt.

A task starts in the **inbox** (the shared queue across all projects) and can sit there indefinitely. When you're ready, assign it to a project and dispatch.

## Project

A **project** is a long-term context container, usually backed by a git repo. Many tasks live inside one project, and the project accumulates memory across sessions, lessons get rolled into `PROGRESS.md` and picked up by future agents automatically.

You don't need to plan projects in advance. One catch-all project (`random-things`, `misc`) is a fine starting point; you can split things out later as patterns emerge.

## Agent

An **agent** is a temporary worker, a Claude Code session, spawned when you dispatch a task. It runs inside the project's directory (or an isolated git worktree), does the work, and persists its conversation as a session. The agent ends; the task and project remain.

Agents are not something you "set up" in advance, they aren't workers you provision in a queue. They come and go, called in when there's work to do.

## Why three layers

Each object has a different lifespan and a different role:

| Object | Lifespan | What it carries |
|---|---|---|
| **Task** | Days to months | One unit of work, retried as needed |
| **Project** | Lifetime of the codebase | Long-term memory, per-project context |
| **Agent** | Minutes to hours | One execution attempt, archived as a session |

Visually:

```
   PROJECT  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶   (forever)
                │           │            │
   TASK         ●───────────●────────────●──── done    (days–months)
                │           │            │
   AGENT      [ run ]   [ retry ]    [ retry ]         (minutes–hours)
```

Keeping these separate means an agent can fail without taking the task with it. You retry with a summary of what was tried, and the project carries forward what was learned, instead of every conversation starting from zero.

## See also

- [Getting Started](getting-started.md): the beginner walkthrough
- [README · The Loop](../README.md#the-loop): the five-step workflow
