# Desktop acceptance

The source-checkout launcher opens `hostrun.desktop` using pythonw. Native Tk widgets integrate the existing Console reader/output seams and the embedded Pi event stream. No release tag was published; packaged CPython still needs Tkinter before desktop distribution can be supported.

Validation: 49 focused tests passed, including native Tk widget creation, session persistence, streamed event rendering, sidebar toggling, Console initialization and embedded Pi integration. The sandbox full suite had 923 passed, 82 failed, 3 skipped; failures include missing platform architecture in distribution compatibility checks. The unrestricted Windows full suite subsequently passed: 1007 passed, 3 skipped, with two cache-write warnings.

Live acceptance remains pending: automated window inventory did not expose the launched Frontier window. Actual model-provider conversation and interactive Feishu workflows were not exercised. Do not interpret source deployment or focused tests as live acceptance.

