## Install

**Claude Code** — install as plugins via the [Bonsai marketplace](https://github.com/bonsai/claude-plugins):

```bash
claude plugin marketplace add bonsai/claude-plugins
claude plugin install search
```

**Other agents** — install as standalone skills:

```bash
npx skills add basecamp/house-skills
```

## Skills

| Skill                               | Plugin | Description                                                                                           |
| ----------------------------------- | ------ | ----------------------------------------------------------------------------------------------------- |
| [autocomplete](skills/autocomplete) | search | Quickly integrate an autocomplete solution into your existing OpenSearch or Elasticsearch powered app |

## Structure

Real skill files live in `plugins/{plugin}/skills/`. The top-level `skills/` directory contains symlinks for a unified view. See [AGENTS.md](AGENTS.md) for details.

## Third-Party Notice

Inspired by [Basecamp's Dev Skills](https://github.com/basecamp/house-skills) under MIT licence.
