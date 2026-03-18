# Contributing to ARIA

## Repository structure

    backend/    Go server and Python ML workers
    frontend/   Next.js user interface
    ml/         Model training scripts
    shared/     Shared TypeScript types
    docs/       Architecture documentation

## Development setup

See README.md for full setup instructions.

## Branch strategy

Development happens on feature branches off integration.
The integration branch is the main development branch.
Releases are tagged on integration.

Branch naming:
  feat/description   — new features
  fix/description    — bug fixes
  docs/description   — documentation only
  chore/description  — maintenance tasks

## Commit conventions

All commits follow conventional commits format:
  feat(scope): description
  fix(scope): description
  docs(scope): description
  test(scope): description
  chore(scope): description
  refactor(scope): description

Scope is the module affected: vision, audio, cognition, tts,
server, frontend, config, etc.

No emoji in commit messages, code, comments, or documentation.

## Code standards

Python: ruff for linting, mypy for type checking, pytest for tests.
Go: go vet, go test for all packages before committing.
TypeScript: eslint, tsc --noEmit before committing.

## Testing

Run before every commit:
  cd backend && python -m pytest tests/ -v
  cd backend && go test ./...
  cd frontend && npm run type-check

## Module ownership

  backend/cmd/, backend/internal/   Go server
  backend/app/pipeline/             Python ML workers
  backend/app/cognition/            LLM and memory (planned)
  frontend/src/                     Next.js UI
  ml/                               Model training
