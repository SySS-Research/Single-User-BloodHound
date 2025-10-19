# dockerhound

Run [BloodHound CE](https://github.com/SpecterOps/BloodHound) as a
single-user application using containers. This tool manages the required
PostgreSQL and Neo4j databases automatically, with no manual setup
needed.

The project was first designed as a single bash script and evolved into
a packaged Python project. The bash script has beend preserved in
`bloodhound-ce` for those who prefer a simpler setup.

## Why dockerhound?

BloodHound CE typically requires setting up multiple services. dockerhound
packages everything into containers with sensible defaults:

- Default credentials: `admin/admin` (no password change required)
- Automatic database initialization
- Isolated workspaces for different projects
- Podman preferred, Docker supported

If you have only podman and uv installed, you can run BloodHound instantly:

```bash
$ uv tool run dockerhound
...
Running postgres container ...
Running neo4j container ...
Wait until neo4j is ready ...
Running bloodhound container ...
Wait until bloodhound is ready ...
Success! Go to http://localhost:8181
Login with admin/admin
Workspace: default
Press CTRL-C when you're done.
...
```

## Installation

```bash
# Using uv (recommended):
uv tool install dockerhound

# Using pipx:
pipx install dockerhound
```

Or install from source:

```bash
git clone <repository>
cd dockerhound
# Using uv (recommended):
uv tool install .

# Usinv pipx:
pipx install .
```

Requires either podman or docker installed. Podman is preferred.

## Usage

Start BloodHound CE:

```bash
dockerhound
```

This will:
1. Start PostgreSQL and Neo4j containers
2. Wait for services to be ready
3. Launch BloodHound CE on <http://localhost:8181>
4. Set up admin credentials (admin/admin)

### Options

- `--port` / `-p`: Change web interface port (default: 8181)
- `--workspace` / `-w`: Use a specific workspace (default: "default")
- `--backend`: Force container backend (`podman` or `docker`)
- `--bolt-port`: Expose Neo4j bolt port (default: 7687, only exposed if specified)
- `--data-dir`: Custom data directory path

### Commands

Pull latest images:

```bash
dockerhound pull
```

### Environment Variables

- `PORT`: Override web interface port
- `WORKSPACE`: Override workspace name
- `DATA_DIR`: Override data directory location

## Workspaces

Workspaces keep different BloodHound databases separate. Each workspace has its own:

- Neo4j graph database
- PostgreSQL application database
- Data stored in `~/.local/share/dockerhound/<workspace>/`

Switch workspaces:

```bash
# Use client1 workspace
dockerhound --workspace client1

# Or with environment variable
WORKSPACE=client1 dockerhound
```

## Examples

```bash
# Default setup
dockerhound

# Different port and workspace
dockerhound --port 9090 --workspace pentest-2024

# Expose Neo4j bolt port for external tools
dockerhound --bolt-port 7687

# Use docker instead of podman
dockerhound --backend docker

# Custom data location
dockerhound --data-dir ./bloodhound-data
```

## Cleanup

Remove containers and data:

```bash
podman container rm --filter name='DockerHound-CE*'
rm -rf ~/.local/share/dockerhound/
```
