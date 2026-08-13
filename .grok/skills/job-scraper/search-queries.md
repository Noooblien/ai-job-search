# Search Queries for Job Scraper

<!-- Personalized for Rahul Singh Maraskole — Lead / Protocol Blockchain Engineer, India Remote -->

## Installed portal CLIs (primary for `/scrape`)

`/scrape` discovers every portal skill under `.agents/skills/*/SKILL.md` and runs its CLI first. Shipped country-agnostic CLIs include `linkedin-search` and `freehire-search`; Danish demos and any skill you add with `/add-portal` are included the same way. You do **not** need a matching `site:` line below for those CLIs to run.

The `site:` query templates in this file are the **web_search fallback** — for portals without a CLI, company career pages, or when a CLI fails.

## Search Sites

Primary:
- **linkedin.com/jobs** — filter: Remote, India, Worldwide remote (also `linkedin-search` CLI)
- **freehire.dev** — tech aggregator (`freehire-search` CLI)
- **wellfound.com / angel.co**, **cryptocurrencyjobs.co**, **web3.career**, **careers pages** of protocol teams

Secondary (company career pages via Google):
- Direct Google searches with `site:` filters for target protocol / infra companies

## Query Categories

### Priority 1: Protocol / Lead Blockchain Engineer

These match the strongest career direction.

```
site:linkedin.com/jobs "Protocol Engineer" blockchain remote
site:linkedin.com/jobs "Blockchain Engineer" "Lead" remote
site:linkedin.com/jobs "Senior Blockchain" engineer remote
"shared sequencer" OR "data availability" OR rollup engineer remote
site:web3.career protocol engineer
site:cryptocurrencyjobs.co protocol OR infrastructure
```

### Priority 2: L2 / Modular / Cosmos / Cross-chain

```
site:linkedin.com/jobs "Cosmos SDK" engineer
site:linkedin.com/jobs rollup OR "Layer 2" engineer remote
site:linkedin.com/jobs "cross-chain" OR IBC engineer
"MEV" sequencer engineer remote
site:linkedin.com/jobs "Hyperledger" Fabric OR Besu engineer
```

### Priority 3: Infrastructure / Indexing / Platform

```
site:linkedin.com/jobs "blockchain infrastructure" remote
site:linkedin.com/jobs indexer OR "node infrastructure" blockchain
site:linkedin.com/jobs Golang Rust blockchain engineer remote
site:linkedin.com/jobs "smart contract" engineer Solidity senior remote
```

### Priority 4: AI × Crypto / Agent infrastructure

```
site:linkedin.com/jobs "AI agent" blockchain OR crypto engineer
site:linkedin.com/jobs decentralized compute OR "verifiable compute"
"autonomous agent" on-chain OR trustless engineer remote
```

## Location Filter

Acceptable:
- Remote (global remote-friendly roles)
- India remote / hybrid if desired
- On-site only outside India: only if user explicitly wants relocation/visa

Reject / flag:
- Strict on-site US/EU with citizenship/PR requirement and no remote (eligibility gate)
- Unpaid "contributor" or pure equity-only without discussion

## Date Filter

Only include jobs posted within the last 14 days, or with an application deadline that has not yet passed. If a posting date cannot be determined, include it but flag as "date unknown".

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus. Examples:
- "Cosmos" → prioritize Cosmos SDK / IBC / CosmWasm
- "enterprise" → Hyperledger Fabric / Besu / Canton / DAML
- "AI agents" → Priority 4 queries
