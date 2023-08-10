 Single User BloodHound CE
==========================

This runs [BloodHound CE](https://github.com/SpecterOps/BloodHound) as if it
were a single, self-contained app in a single-user scenario.

It's based on SpecterOp's
[Dockerfile](https://github.com/SpecterOps/BloodHound/blob/294dab1f72fb3fcbaf7d010fd7ee9301f6ba78fe/dockerfiles/bloodhound.Dockerfile),
but uses podman, sets the default credentials to **admin/admin** (no password
change needed) and exposes port 8181 on localhost only.

No dependencies except for podman (and `bash`, `grep` and `date`)!

Simply run `./bloodhound-su`. Link or copy it to `~/.local/bin` or
`/usr/bin` if you want.

It supports workspaces to keep different databases in parallel. They're
located in `$XDG_DATA_HOME/SingleUserBloodHound`
(or `~/.local/share/SingleUserBloodHound` by
default). To set the name of the workspace, use environment variables:

```console
$ WORKSPACE=client1 bloodhound-su
```

The location of the workspace's data directory can be set directly like so:

```console
$ DATA_DIR=BH_DATA bloodhound-su
```

Then the data will be stored in `BH_DATA` in the current working directory.
The port to listen on can similarly be changed by setting `$PORT`.

In case you want to start over completely, delete the containers and volumes:
```console
$ podman container rm --filter name='SingleUserBloodHound*'
$ rm -rf ~/.local/share/SingleUserBloodHound/
```
