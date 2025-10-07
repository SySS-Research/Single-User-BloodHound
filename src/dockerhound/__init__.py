#!/usr/bin/env python3
"""
DockerHound
Python CLI implementation of the BloodHound CE containerized deployment.

MIT License - Copyright (c) 2023-2025 SySS Research, Adrian Vollmer
"""

import os
import sys
import signal
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import click


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    NC = "\033[0m"


class BloodHoundCE:
    def __init__(
        self,
        backend: str = "podman",
        port: int = 8181,
        workspace: str = "default",
        data_dir: Optional[str] = None,
        bolt_port: Optional[int] = None,
    ):
        self.backend = backend
        self.port = port
        self.bolt_port = bolt_port
        self.workspace = workspace

        if data_dir:
            self.data_dir = Path(data_dir).resolve()
        else:
            xdg_data_home = os.environ.get(
                "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
            )
            self.data_dir = Path(xdg_data_home) / "dockerhound" / workspace

        self.neo4j_vol = self.data_dir / "neo4j"
        self.postgres_vol = self.data_dir / "postgres"
        self.network = "DockerHound-CE-network"

        # Credentials
        self.admin_name = "admin"
        self.admin_password = "admin"

        # Images
        self.bloodhound_image = f"docker.io/specterops/bloodhound:{os.environ.get('BLOODHOUND_TAG', 'latest')}"
        self.neo4j_image = "docker.io/library/neo4j:4.4"
        self.postgres_image = "docker.io/library/postgres:16"

        # Container names
        self.bloodhound_container = "DockerHound-CE_BH"
        self.neo4j_container = "DockerHound-CE_Neo4j"
        self.postgres_container = "DockerHound-CE_PSQL"

        self.timestamp = str(int(time.time()))

        # Set up signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print("\nStopping containers ...")
        self._stop_containers()
        sys.exit(0)

    def _run_command(
        self, cmd: list[str], capture_output: bool = False, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a command with the selected backend."""
        try:
            if capture_output:
                return subprocess.run(cmd, capture_output=True, text=True, check=check)
            else:
                return subprocess.run(cmd, stdout=subprocess.DEVNULL, check=check)
        except subprocess.CalledProcessError as e:
            print(f"{Colors.RED}Command failed: {' '.join(cmd)}{Colors.NC}")
            if capture_output and e.stderr:
                print(f"{Colors.RED}{e.stderr}{Colors.NC}")
            raise

    def _container_exists(self, name: str) -> bool:
        """Check if a container exists."""
        try:
            result = self._run_command(
                [self.backend, "container", "exists", name], check=False
            )
            return result.returncode == 0
        except Exception:
            return False

    def _network_exists(self) -> bool:
        """Check if the network exists."""
        try:
            result = self._run_command(
                [self.backend, "network", "exists", self.network], check=False
            )
            return result.returncode == 0
        except Exception:
            return False

    def setup_directories(self):
        """Create necessary directories."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.neo4j_vol.mkdir(parents=True, exist_ok=True)
        self.postgres_vol.mkdir(parents=True, exist_ok=True)

    def setup_network(self):
        """Create the container network if it doesn't exist."""
        if not self._network_exists():
            self._run_command([self.backend, "network", "create", self.network])

    def pull_images(self):
        """Pull all required container images."""
        images = [self.bloodhound_image, self.neo4j_image, self.postgres_image]
        for image in images:
            print(f"Pulling {image}...")
            self._run_command([self.backend, "pull", image])

    def run_postgres(self):
        """Start the PostgreSQL container."""
        print("Running postgres container ...")
        cmd = [
            self.backend,
            "run",
            "--rm",
            "--replace",
            "--detach",
            "--net",
            self.network,
            "--network-alias",
            "app-db",
            "--name",
            self.postgres_container,
            "--volume",
            f"{self.postgres_vol}:/var/lib/postgresql/data",
            "-e",
            "PGUSER=bloodhound",
            "-e",
            "POSTGRES_USER=bloodhound",
            "-e",
            "POSTGRES_PASSWORD=bloodhoundcommunityedition",
            "-e",
            "POSTGRES_DB=bloodhound",
            self.postgres_image,
        ]
        self._run_command(cmd)

    def run_neo4j(self):
        """Start the Neo4j container."""
        print("Running neo4j container ...")
        cmd = [
            self.backend,
            "run",
            "--rm",
            "--detach",
            "--replace",
            "--net",
            self.network,
            "--network-alias",
            "graph-db",
            "--name",
            self.neo4j_container,
            "--volume",
            f"{self.neo4j_vol}:/data",
            "--publish",
            "127.0.0.1:7474:7474",
        ]

        # Only expose bolt port if explicitly requested
        if self.bolt_port is not None:
            cmd.extend(["--publish", f"127.0.0.1:{self.bolt_port}:7687"])

        cmd.extend(
            [
                "-e",
                "NEO4J_AUTH=neo4j/bloodhoundcommunityedition",
                self.neo4j_image,
            ]
        )
        self._run_command(cmd)

    def run_bloodhound(self):
        """Start the BloodHound container."""
        print("Running bloodhound container ...")
        cmd = [
            self.backend,
            "run",
            "--rm",
            "--replace",
            "--detach",
            "--net",
            self.network,
            "--network-alias",
            "bloodhound",
            "--name",
            self.bloodhound_container,
            "--publish",
            f"127.0.0.1:{self.port}:8080",
            "-e",
            f"bhe_disable_cypher_qc={os.environ.get('bhe_disable_cypher_qc', 'false')}",
            "-e",
            "bhe_database_connection=user=bloodhound password=bloodhoundcommunityedition dbname=bloodhound host=app-db",
            "-e",
            "bhe_neo4j_connection=neo4j://neo4j:bloodhoundcommunityedition@graph-db:7687/",
            "-e",
            f"bhe_default_admin_principal_name={self.admin_name}",
            "-e",
            f"bhe_default_admin_password={self.admin_password}",
            self.bloodhound_image,
        ]
        self._run_command(cmd)

    def wait_for_neo4j(self):
        """Wait for Neo4j to be ready."""
        print("Wait until neo4j is ready ...")
        while True:
            time.sleep(1)
            try:
                result = self._run_command(
                    [
                        self.backend,
                        "logs",
                        "--since",
                        self.timestamp,
                        self.neo4j_container,
                    ],
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    logs = result.stdout
                    if "Remote interface available at http://localhost:7474/" in logs:
                        break
                    if "Error" in logs:
                        print(logs)
                        print(f"{Colors.RED}Neo4j container failed{Colors.NC}")
                        sys.exit(1)
            except Exception:
                continue

    def wait_for_bloodhound(self):
        """Wait for BloodHound to be ready."""
        print("Wait until bloodhound is ready ...")
        while True:
            time.sleep(1)
            try:
                result = self._run_command(
                    [
                        self.backend,
                        "logs",
                        "--since",
                        self.timestamp,
                        self.bloodhound_container,
                    ],
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    logs = result.stdout
                    if "Server started successfully" in logs:
                        break
                    if any(
                        pattern in logs
                        for pattern in ['"level":"error"', '"level":"fatal"', "Error: "]
                    ):
                        print(logs)
                        print(f"{Colors.RED}BloodHound container failed{Colors.NC}")
                        sys.exit(1)
            except Exception:
                continue

    def set_password_expiry(self):
        """Set the admin password to not expire for a year."""
        expiry = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d 00:00:00+00")
        cmd = [
            self.backend,
            "exec",
            self.postgres_container,
            "psql",
            "-q",
            "-U",
            "bloodhound",
            "-d",
            "bloodhound",
            "-c",
            f"UPDATE auth_secrets SET expires_at='{expiry}' WHERE id='1';",
        ]
        self._run_command(cmd)

    def _stop_containers(self):
        """Stop all containers."""
        containers = [self.neo4j_container, self.postgres_container]
        for container in containers:
            try:
                self._run_command([self.backend, "stop", "-i", container], check=False)
            except Exception:
                pass

    def attach_to_bloodhound(self):
        """Attach to BloodHound container for monitoring."""
        try:
            # Show logs first
            result = self._run_command(
                [
                    self.backend,
                    "logs",
                    "--since",
                    self.timestamp,
                    self.bloodhound_container,
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                print(result.stdout)

            # Attach to container (this will block until interrupted)
            subprocess.run([self.backend, "attach", self.bloodhound_container])
        except KeyboardInterrupt:
            pass

    def run(self):
        """Main execution flow."""
        self.setup_directories()
        self.setup_network()

        # Start containers
        self.run_postgres()
        self.run_neo4j()

        # Wait for Neo4j (PostgreSQL is typically faster)
        self.wait_for_neo4j()

        # Start BloodHound
        self.run_bloodhound()
        self.wait_for_bloodhound()

        # Configure password expiry
        self.set_password_expiry()

        # Success message
        print(f"{Colors.GREEN}Success! Go to http://localhost:{self.port}{Colors.NC}")
        print(
            f"{Colors.GREEN}Login with {self.admin_name}/{self.admin_password}{Colors.NC}"
        )
        print(f"Workspace: {self.workspace}")
        print("Press CTRL-C when you're done.")

        # Attach to container for log monitoring
        self.attach_to_bloodhound()


def detect_backend() -> str:
    """Detect available container backend, preferring podman."""
    for backend in ["podman", "docker"]:
        try:
            result = subprocess.run(
                [backend, "--version"], capture_output=True, check=False
            )
            if result.returncode == 0:
                return backend
        except FileNotFoundError:
            continue

    print(
        f"{Colors.RED}Neither podman nor docker found. Please install one of them.{Colors.NC}"
    )
    sys.exit(1)


@click.command()
@click.option(
    "--backend",
    type=click.Choice(["podman", "docker"]),
    help="Container backend to use (default: auto-detect, preferring podman)",
)
@click.option(
    "--port",
    "-p",
    default=8181,
    type=int,
    help="Port to expose BloodHound on (default: 8181)",
)
@click.option(
    "--workspace",
    "-w",
    default="default",
    help="Workspace name for data isolation (default: default)",
)
@click.option(
    "--data-dir",
    type=click.Path(),
    help="Custom data directory path (overrides workspace)",
)
@click.option(
    "--bolt-port",
    type=int,
    help="Port to expose Neo4j bolt protocol on (default: 7687, only exposed if specified)",
)
@click.argument("command", default="run", type=click.Choice(["run", "pull"]))
def main(
    backend: Optional[str],
    port: int,
    workspace: str,
    data_dir: Optional[str],
    bolt_port: Optional[int],
    command: Optional[str],
) -> None:
    """Single User BloodHound CE - Run BloodHound Community Edition in containers."""

    # Override with environment variables if set
    port = int(os.environ.get("PORT", port))
    workspace = os.environ.get("WORKSPACE", workspace)
    if "DATA_DIR" in os.environ:
        data_dir = os.environ["DATA_DIR"]

    # Detect backend if not specified
    if not backend:
        backend = detect_backend()

    bh = BloodHoundCE(
        backend=backend,
        port=port,
        workspace=workspace,
        data_dir=data_dir,
        bolt_port=bolt_port,
    )

    if command == "pull":
        bh.pull_images()
        return

    bh.run()


if __name__ == "__main__":
    main()
