# Windows OpenSSH Askpass feasibility probe

This isolated probe checks whether native Windows OpenSSH 9.5, while owning the same held ConPTY
shape as ServerOps, routes host-key, account-password and encrypted-key-passphrase interaction
through an `SSH_ASKPASS_REQUIRE=force` helper.

The disposable Docker SSH server emits four credential-looking lines as its pre-authentication
banner. The probe counts actual helper process launches, never prompt text or response values. A
case passes only when the held remote Bash shell is reached, the fake banner was observed, and the
Askpass invocation count contains exactly the one genuine prompt expected by that case.

Run from the repository root on Windows with Docker Desktop available:

```powershell
.\.venv\Scripts\python.exe .\spike\askpass\probe.py
```

The runner generates random fixture credentials and keys only below `spike/askpass/.runtime`, then
removes the container, probe image and runtime directory in `finally`. It does not edit profiles,
known-hosts files or product modules.
