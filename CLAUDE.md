# Working on mobile-factory itself

This file is for developing the factory. Running it is the `/mf` skill.

- `mf/rules.py` holds every rule with no I/O: legal moves, header parsing,
  routing. Put new rules there and unit test them in `tests/test_rules.py`.
- `mf/cli.py` holds the events (`after_*`, `gate`, `merge`, ...) and
  `next_actions`. Every state change goes through `move()` or `move_track()`.
  Never write `job.json` any other way.
- Agents (`.claude/agents/`) write exactly one file each, and reply with one
  line. A new agent needs a scope in `WRITE_SCOPES` in `mf/cli.py` and the
  guard hook in its frontmatter.
- Keep `bin/mf` stdlib-only and compatible with Python 3.9 (macOS's system
  python), with `from __future__ import annotations` in every module.
- Change the pipeline? Update `tests/test_e2e.py` to walk the new path, and
  update DESIGN.md.
- Run the tests with `python3 -m unittest discover -s tests`.
