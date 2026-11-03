# Coding standards

What a review checks beyond `./tests/run`. These are judgement calls; anything a check can catch belongs in the suite instead. [CONTRIBUTING.md](CONTRIBUTING.md) has the pull request rules.

## The contract moves with the behaviour

A change to what a backend script reads, computes, saves or returns updates its contract in the same change: [docs/backend-contract.md](docs/backend-contract.md) for limits, [docs/cost-contract.md](docs/cost-contract.md) for costs. Reread every sentence about the behaviour the diff touches, not only the one you meant to change: a contract that still describes the old behaviour is a bug.

## A ceiling shows up as partial

Every input has a ceiling (records, files, bytes, time). When one stops a read, the source reports partial coverage with a message that says what was left out. A total computed past a ceiling is never presented as complete, and a ceiling is sized for a heavy user, not a typical one: a computer running agents all day writes about 160,000 billed messages a month.

## Counted once, wherever it was read

The same account read by two sources is one row, and the same message recorded in two places is one record. A change to what another computer or a proxy sends (its shape, grouping or ids) keeps what deduplication across sources needs, or the review states what can now count twice and why that is acceptable.

## Credentials travel over https

Any address that can come from the environment or settings and receives a token, key or cookie is checked before the first request: `https`, no user name or password, no query or fragment. Plain HTTP carries a secret only through `quotatank_common.secret_opener` and its checked routes. The error says which setting to fix and that nothing was sent.

## The panel holds still

Text or a control that appears and disappears with a read, a request or a timer keeps its place while it can come back, or lives in a line that is always there (the footer). Nothing below it moves when it changes.
