# Contributing to MediaFlow Proxy

First off, thanks for taking the time to contribute! 🎉

## Code Style

We use `black` for formatting and `ruff` for linting. Please ensure your code passes these checks before submitting a PR.

```bash
# Install dev dependencies
poetry install

# Format code
poetry run black .

# Lint code
poetry run ruff check .
```

## Pull Request Process

1.  Fork the repository and create your branch from `main`.
2.  If you've added code that should be tested, add tests.
3.  Ensure the test suite passes.
4.  Make sure your code lints.
5.  Issue that pull request!

## Developing a New Extractor

1.  Create a new file in `mediaflow_proxy/extractors/`.
2.  Inherit from `BaseExtractor`.
3.  Implement `can_handle` and `extract` methods.
4.  Register your extractor in `mediaflow_proxy/extractors/factory.py`.

## Reporting Bugs

Please include the following in your bug report:
-   Your OS and Python version.
-   Steps to reproduce the bug.
-   Expected behavior vs actual behavior.
-   Logs/Traceback (please redact secrets!).
