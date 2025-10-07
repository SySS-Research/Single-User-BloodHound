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
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import click


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    NC = "\033[0m"


# Constants
DEFAULT_PORT = 8181
DEFAULT_WORKSPACE = "default"
DEFAULT_ADMIN_NAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"

# Container configuration
BLOODHOUND_IMAGE_TEMPLATE = "docker.io/specterops/bloodhound:{}"
NEO4J_IMAGE = "docker.io/library/neo4j:4.4"
POSTGRES_IMAGE = "docker.io/library/postgres:16"

# Network and container names
NETWORK_NAME = "DockerHound-CE-network"
BLOODHOUND_CONTAINER = "DockerHound-CE_BH"
NEO4J_CONTAINER = "DockerHound-CE_Neo4j"
POSTGRES_CONTAINER = "DockerHound-CE_PSQL"

# Database configuration
DB_USER = "bloodhound"
DB_PASSWORD = "bloodhoundcommunityedition"
DB_NAME = "bloodhound"
NEO4J_AUTH = "neo4j/bloodhoundcommunityedition"


@dataclass
class Config:
    """Configuration for BloodHound CE deployment."""
    backend: str
    port: int
    bolt_port: Optional[int]
    workspace: str
    data_dir: Path
    
    # Derived paths
    neo4j_vol: Path
    postgres_vol: Path
    
    # Credentials
    admin_name: str
    admin_password: str
    
    # Images
    bloodhound_image: str
    neo4j_image: str = NEO4J_IMAGE
    postgres_image: str = POSTGRES_IMAGE
    
    # Container and network names
    network: str = NETWORK_NAME
    bloodhound_container: str = BLOODHOUND_CONTAINER
    neo4j_container: str = NEO4J_CONTAINER
    postgres_container: str = POSTGRES_CONTAINER
    
    @classmethod
    def create(
        cls,
        backend: str,
        port: int = DEFAULT_PORT,
        workspace: str = DEFAULT_WORKSPACE,
        data_dir: Optional[str] = None,
        bolt_port: Optional[int] = None,
    ) -> "Config":
        """Create configuration with environment variable overrides."""
        # Apply environment variable overrides
        port = int(os.environ.get("PORT", port))
        workspace = os.environ.get("WORKSPACE", workspace)
        data_dir = os.environ.get("DATA_DIR", data_dir)
        
        # Determine data directory
        if data_dir:
            data_path = Path(data_dir).resolve()
        else:
            xdg_data_home = os.environ.get(
                "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
            )
            data_path = Path(xdg_data_home) / "dockerhound" / workspace
        
        # Get BloodHound image with tag
        bloodhound_tag = os.environ.get("BLOODHOUND_TAG", "latest")
        bloodhound_image = BLOODHOUND_IMAGE_TEMPLATE.format(bloodhound_tag)
        
        # Get admin credentials
        admin_name = os.environ.get("ADMIN_NAME", DEFAULT_ADMIN_NAME)
        admin_password = os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
        
        return cls(
            backend=backend,
            port=port,
            bolt_port=bolt_port,
            workspace=workspace,
            data_dir=data_path,
            neo4j_vol=data_path / "neo4j",
            postgres_vol=data_path / "postgres",
            admin_name=admin_name,
            admin_password=admin_password,
            bloodhound_image=bloodhound_image,
        )


class BloodHoundCE:
    def __init__(self, config: Config):
        self.config = config
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
                [self.config.backend, "container", "exists", name], check=False
            )
            return result.returncode == 0
        except Exception:
            return False

    def _network_exists(self) -> bool:
        """Check if the network exists."""
        try:
            result = self._run_command(
                [self.config.backend, "network", "exists", self.config.network], check=False
            )
            return result.returncode == 0
        except Exception:
            return False

    def setup_directories(self):
        """Create necessary directories."""
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.neo4j_vol.mkdir(parents=True, exist_ok=True)
        self.config.postgres_vol.mkdir(parents=True, exist_ok=True)

    def setup_network(self):
        """Create the container network if it doesn't exist."""
        if not self._network_exists():
            self._run_command([self.config.backend, "network", "create", self.config.network])

    def pull_images(self):
        """Pull all required container images."""
        images = [self.config.bloodhound_image, self.config.neo4j_image, self.config.postgres_image]
        for image in images:
            print(f"Pulling {image}...")
            self._run_command([self.config.backend, "pull", image])

    def run_postgres(self):
        """Start the PostgreSQL container."""
        print("Running postgres container ...")
        cmd = [
            self.config.backend,
            "run",
            "--rm",
            "--replace",
            "--detach",
            "--net",
            self.config.network,
            "--network-alias",
            "app-db",
            "--name",
            self.config.postgres_container,
            "--volume",
            f"{self.config.postgres_vol}:/var/lib/postgresql/data",
            "-e",
            f"PGUSER={DB_USER}",
            "-e",
            f"POSTGRES_USER={DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-e",
            f"POSTGRES_DB={DB_NAME}",
            self.config.postgres_image,
        ]
        self._run_command(cmd)

    def run_neo4j(self):
        """Start the Neo4j container."""
        print("Running neo4j container ...")
        cmd = [
            self.config.backend,
            "run",
            "--rm",
            "--detach",
            "--replace",
            "--net",
            self.config.network,
            "--network-alias",
            "graph-db",
            "--name",
            self.config.neo4j_container,
            "--volume",
            f"{self.config.neo4j_vol}:/data",
            "--publish",
            "127.0.0.1:7474:7474",
        ]

        # Only expose bolt port if explicitly requested
        if self.config.bolt_port is not None:
            cmd.extend(["--publish", f"127.0.0.1:{self.config.bolt_port}:7687"])

        cmd.extend(
            [
                "-e",
                f"NEO4J_AUTH={NEO4J_AUTH}",
                self.config.neo4j_image,
            ]
        )
        self._run_command(cmd)

    def run_bloodhound(self):
        """Start the BloodHound container."""
        print("Running bloodhound container ...")
        cmd = [
            self.config.backend,
            "run",
            "--rm",
            "--replace",
            "--detach",
            "--net",
            self.config.network,
            "--network-alias",
            "bloodhound",
            "--name",
            self.config.bloodhound_container,
            "--publish",
            f"127.0.0.1:{self.config.port}:8080",
            "-e",
            f"bhe_disable_cypher_qc={os.environ.get('bhe_disable_cypher_qc', 'false')}",
            "-e",
            f"bhe_database_connection=user={DB_USER} password={DB_PASSWORD} dbname={DB_NAME} host=app-db",
            "-e",
            f"bhe_neo4j_connection=neo4j://{NEO4J_AUTH}@graph-db:7687/",
            "-e",
            f"bhe_default_admin_principal_name={self.config.admin_name}",
            "-e",
            f"bhe_default_admin_password={self.config.admin_password}",
            self.config.bloodhound_image,
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
                        self.config.backend,
                        "logs",
                        "--since",
                        self.timestamp,
                        self.config.neo4j_container,
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
                        self.config.backend,
                        "logs",
                        "--since",
                        self.timestamp,
                        self.config.bloodhound_container,
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
            self.config.backend,
            "exec",
            self.config.postgres_container,
            "psql",
            "-q",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-c",
            f"UPDATE auth_secrets SET expires_at='{expiry}' WHERE id='1';",
        ]
        self._run_command(cmd)

    def _stop_containers(self):
        """Stop all containers."""
        containers = [self.config.neo4j_container, self.config.postgres_container]
        for container in containers:
            try:
                self._run_command([self.config.backend, "stop", "-i", container], check=False)
            except Exception:
                pass

    def attach_to_bloodhound(self):
        """Attach to BloodHound container for monitoring."""
        try:
            # Show logs first
            result = self._run_command(
                [
                    self.config.backend,
                    "logs",
                    "--since",
                    self.timestamp,
                    self.config.bloodhound_container,
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                print(result.stdout)

            # Attach to container (this will block until interrupted)
            subprocess.run([self.config.backend, "attach", self.config.bloodhound_container])
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
        print(f"{Colors.GREEN}Success! Go to http://localhost:{self.config.port}{Colors.NC}")
        print(
            f"{Colors.GREEN}Login with {self.config.admin_name}/{self.config.admin_password}{Colors.NC}"
        )
        print(f"Workspace: {self.config.workspace}")
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

    # Detect backend if not specified
    if not backend:
        backend = detect_backend()

    # Create configuration with environment variable handling
    config = Config.create(
        backend=backend,
        port=port,
        workspace=workspace,
        data_dir=data_dir,
        bolt_port=bolt_port,
    )

    bh = BloodHoundCE(config)

    if command == "pull":
        bh.pull_images()
        return

    bh.run()


if __name__ == "__main__":
    main()
