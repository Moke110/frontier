# Desktop acceptance

The source-checkout launcher opens `hostrun.desktop` using pythonw. Native Tk widgets integrate the existing Console reader/output seams and the embedded Pi event stream. No release tag was published; packaged CPython still needs Tkinter before desktop distribution can be supported.

Validation: 49 focused tests passed, including native Tk widget creation, session persistence, streamed event rendering, sidebar toggling, Console initialization and embedded Pi integration. The sandbox full suite had 923 passed, 82 failed, 3 skipped; failures include missing platform architecture in distribution compatibility checks. The unrestricted Windows full suite subsequently passed: 1007 passed, 3 skipped, with two cache-write warnings.

Live acceptance remains pending: automated window inventory did not expose the launched Frontier window. Actual model-provider conversation and interactive Feishu workflows were not exercised. Do not interpret source deployment or focused tests as live acceptance.


Startup recovery: removed the two confirmed desktop test processes left running on an inaccessible desktop. The Explorer-launched window was observed through Windows UI Automation as `Frontier — Research Agent`. Repeated launches now request deiconify/lift/focus via an activation file; a Tk regression test verifies restoration from a withdrawn window. Actual model-provider and Feishu acceptance remain pending.

## Windows desktop process lifecycle — 2026-11-07

- Terminated the identified pre-existing Frontier GUI tree (34728 / 36608 and children), plus all diagnostic GUI instances created during this change.
- Installed local Frontier.lnk entries in checkout, parent folder and current-user Start Menu. They target pythonw directly, with no shell wrapper. No global security policy was changed; file-level Unblock-File applied only to launcher/runtime targets.
- 52 focused tests passed: desktop, real Windows normal/forced job cleanup, child GetConsoleWindow == 0, Console, initialization and embedded Agent. Pytest cache emitted one permissions warning.
- Interactive desktop shortcut launch/close acceptance remains pending: Explorer automation had unreliable focus; no successful visible GUI launch was observed in this verification. Do not treat process startup alone as visible GUI acceptance.
- Native .cmd is retained for CLI compatibility and may flash its own console; the supported zero-console entry is Frontier.lnk / Start Menu Frontier.
