# Building the Hello World installer

The application is native C using only Windows system APIs. It neither embeds nor
loads the existing Python business application. Building requires Zig **0.13.0**
and Inno Setup **6.4.3**; end users require neither tool.

```powershell
./installer/build.ps1 -Zig C:/tools/zig/zig.exe -ISCC 'C:/tools/inno/ISCC.exe' -Version 0.1.0-preview.1
```

The executable is `installer/build/Frontier.exe`; running this source-built entry
has exactly the installed entry's behavior. The installer is under
`installer/output/`. Run `python installer/smoke.py <installed-path>/Frontier.exe`
for native console title, output and process-lifetime checks. A visible-console check must additionally
confirm the user-visible appearance; automated native API checks alone do not
prove the graphical user journey.

The installer is per-user, offers directory selection, always adds a Start menu
shortcut, and offers a desktop shortcut. Its stable application ID supports future
upgrades. Only files explicitly installed by Inno Setup are removed on uninstall.
No business configuration or network calls occur during application startup.

Windows 10 and 11 clean-machine, offline installation acceptance remains required;
a developer-machine build or smoke check does not establish that acceptance.
