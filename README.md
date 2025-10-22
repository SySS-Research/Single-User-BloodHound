 Single User BloodHound CE
==========================

This runs [BloodHound CE](https://github.com/SpecterOps/BloodHound) as if it
were a single, self-contained app in a single-user scenario.

It's based on SpecterOp's
[Dockerfile](https://github.com/SpecterOps/BloodHound/blob/294dab1f72fb3fcbaf7d010fd7ee9301f6ba78fe/dockerfiles/bloodhound.Dockerfile),
but uses podman, sets the default credentials to **admin/admin** (no password
change needed) and exposes port 8181 on localhost only.

No dependencies except for podman (and `bash`, `grep` and `date`)!

Simply run `./bloodhound-ce`:


```console
$ ./bloodhound-ce
Running postgres container ...
Running neo4j container ...
Wait until neo4j is ready ...
Running bloodhound container ...
Wait until bloodhound is ready ...
Setting initial password ...
Success! Go to http://localhost:8181
Login with admin/admin
Press CTRL-C when you're done.
...
```

Link or copy the executable to `~/.local/bin` or `/usr/bin` if you want.

It supports workspaces to keep different databases in parallel. They're
located in `$XDG_DATA_HOME/BloodHound-CE`
(or `~/.local/share/BloodHound-CE` by
default). To set the name of the workspace, use environment variables:

```console
$ WORKSPACE=client1 bloodhound-ce
```

The location of the workspace's data directory can be set directly like so:

```console
$ DATA_DIR=BH_DATA bloodhound-ce
```

Then the data will be stored in `BH_DATA` in the current working directory.
The port to listen on can similarly be changed by setting `$PORT`.

## Neo4j GDS Plugin

By default, the script installs the Neo4j Graph Data Science (GDS) plugin,
which is required for certain BloodHound features. If you want to disable this:

```console
$ INSTALL_GDS=false bloodhound-ce
```

To update the images:

```console
$ bloodhound-ce pull
```

In case you want to start over completely, delete the containers and volumes:
```console
$ podman container rm --filter name='BloodHound-CE*'
$ rm -rf ~/.local/share/BloodHound-CE/
```
