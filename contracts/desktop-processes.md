# Desktop process ownership

The user-started GUI owns every background process it creates. No worker may outlive it.

- Before Console/Agent workers start, attach the GUI to a non-inheritable Windows Job Object with KILL_ON_JOB_CLOSE. Descendants inherit job membership; breakaway is prohibited. Failure to establish containment must abort startup.
- The GUI retains the only job handle. Normal exit, crash, and forced termination close that handle and Windows terminates the entire descendant tree. No polling daemon or machine-wide process-name kill is used.
- Closing the window stops accepting new requests, cancels the active agent, signals Console EOF, and allows at most 10 seconds for graceful shutdown. Then the GUI process exits, including if worker threads remain.
- All Python subprocess launches in desktop mode hide their windows. The policy is inherited by hostrun CLI workers through FRONTIER_DESKTOP. Node subprocess calls must set windowsHide: true. New process launch sites must preserve both containment and hidden-window behavior.
- No detached services, scheduled tasks, startup registrations, or breakaway flags may be added for desktop workers. Standalone CLI sessions have their own explicit lifecycle.
- Use the locally generated Frontier.lnk / Start Menu entry for zero-console startup. A .cmd file necessarily invokes cmd.exe and remains a CLI compatibility entry.
- Cleanup of pre-existing processes must identify the exact Frontier invocation and descendants; never kill all python/node/cmd processes by name. Do not delete locks, logs, or archive data as a substitute for stopping their owners.
- Local shortcut installation removes download blocking only from the launcher/runtime files used by the shortcut. It must not disable SmartScreen, Defender, UAC, or global attachment policy.

Verification: tests/test_desktop_processes.py runs isolated real Windows job owners and checks cleanup after both normal and forced exit. GUI startup/close and zero remaining Frontier descendants must also be checked on the interactive desktop.
