## Install

**Claude Code** — install as plugins via the [Bonsai marketplace](https://github.com/omc/search-skills):

```bash
claude plugin marketplace add omc/search-skills
claude plugin install search@bonsai
```

**Other agents** — install as standalone skills:

```bash
npx skills add omc/search-skills
```

## Skills

| Skill                                            | Plugin | Description                                                                                                    |
| ------------------------------------------------ | ------ | -------------------------------------------------------------------------------------------------------------- |
| [autocomplete](skills/bonsai-autocomplete)       | search | Quickly integrate an autocomplete solution into your existing OpenSearch or Elasticsearch powered app          |
| [database-search](skills/bonsai-database-search) | search | Design and implement a unified search index for your app's relational database in Elasticsearch or OpenSearch. |
| [fix-float-bloat](skills/bonsai-fix-float-bloat) | search | Find and fix a float-bloat precision widening bug in your vector search indexing implementation.               |

## Structure

Real skill files live in `plugins/{plugin}/skills/`. The top-level `skills/` directory contains symlinks for a unified view. See [AGENTS.md](AGENTS.md) for details.

## Third-Party Notice

Inspired by [Basecamp's Dev Skills](https://github.com/basecamp/house-skills) under MIT licence.
