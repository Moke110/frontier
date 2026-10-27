"""Host-owned execution layer for frontier.

ADR 0005 moved installation, scheduling and feedback to the host agent: no
services, no OS scheduler entries, no detached listeners, no PATH/registry
writes. This package is that layer and the only place allowed to compose the
domain modules (``library``, ``question_queue``, ``publisher``, ``archive``).

Modules:
  ``install``    capability probes, resumable progress, install report
  ``executor``   single-executor lease and explicit hand-over
  ``feedback``   Feishu-persisted questions / submissions / results
  ``kb``         knowledge-base create or attach, structure verification
  ``schedules``  schedule spec for the host's own scheduler
  ``intents``    bounded runs: daily / feedback / maintenance
  ``audit``      existing-data reconciliation against the migration baseline
"""
