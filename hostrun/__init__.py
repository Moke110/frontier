"""Host-owned execution layer for frontier.

ADR 0005 moved installation, scheduling and feedback to the host agent: no
services, no OS scheduler entries, no PATH/registry writes, and every run is
bounded. The only resident component is the user-started listener (ADR 0008):
a foreground console the user starts and stops by hand, not a service, with no
autostart. This package is that layer and the only place allowed to compose the
domain modules (``library``, ``question_queue``, ``publisher``, ``archive``).

Modules:
  ``install``     install state machine, capability probes and honest report
  ``workspace``   code/data layout, private uv + interpreter, frontier-run pointer
  ``lark``        Lark CLI discovery, login guidance and permission preflight
  ``listener``    the user-started resident loop: Feishu events and feedback polls
  ``console``     the Console shell: single instance, heartbeat, event stream, slash commands
  ``console_events`` the Console's Feishu event surface: two subscriptions, owner gate, 5/10-minute ticks
  ``operations``  the operation registry + exact instruction whitelist and their executors
  ``intent_judgement`` the read-only intent judgement run and its one-time confirmation card
  ``console_service`` the Console's service lifecycle: daily slot, catch-up, pause/resume, control file, shutdown
  ``agent_run``   the Console's Agent run adapter: headless dsh, JSON events, log, lease
  ``facilities``  create/attach Base, tables and Drive folders by confirmed names
  ``smoke``       tagged keyword-driven temporary acceptance
  ``cleanup``     exact test-artifact deletion with read-back verification
  ``initialize``  formal knowledge cards from literature + user requirements
  ``schedules``   the two host tasks and real-trigger evidence
  ``executor``    single-executor lease and explicit hand-over
  ``feedback``    Feishu-persisted questions / submissions / results
  ``kb``          knowledge-base create or attach, structure verification
  ``intents``     bounded runs: daily / feedback / maintenance / listener-check
  ``audit``       existing-data reconciliation against the migration baseline
"""
