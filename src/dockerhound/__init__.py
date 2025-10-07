#!/usr/bin/env python3
"""
DockerHound
Python CLI implementation of the BloodHound CE containerized deployment.

MIT License - Copyright (c) 2023-2025 SySS Research, Adrian Vollmer
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

import logging

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

# Initialize logging with rich handler
FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(show_path=False)]
)

logger = logging.getLogger("dockerhound")


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
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "bloodhoundcommunityedition"


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

    # Debug flag
    debug: bool = False

    @staticmethod
    def _validate_port(port: int, port_name: str) -> None:
        """Validate port number is in valid range."""
        if not (1 <= port <= 65535):
            logger.error(f"{port_name} ({port}) must be between 1 and 65535")
            logger.error("Suggestion: Use a port number like 8080, 8181, or 3000")
            sys.exit(1)
        if port < 1024:
            logger.warning(
                f"Warning: {port_name} ({port}) is a privileged port. You may need sudo"
            )

    @staticmethod
    def _validate_workspace(workspace: str) -> None:
        """Validate workspace name contains only safe characters."""
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", workspace):
            logger.error(f"workspace '{workspace}' contains invalid characters")
            logger.error(
                "Suggestion: Use only letters, numbers, underscores, and hyphens"
            )
            sys.exit(1)

    @staticmethod
    def _validate_data_directory(data_path: Path) -> None:
        """Validate data directory is accessible and writable."""
        try:
            # Check if parent exists and is writable
            if not data_path.parent.exists():
                logger.error(f"Parent directory {data_path.parent} does not exist")
                logger.error(
                    f"Suggestion: Create the parent directory first: mkdir -p {data_path.parent}"
                )
                sys.exit(1)

            if not os.access(data_path.parent, os.W_OK):
                logger.error(f"No write permission for {data_path.parent}")
                logger.error(
                    "Suggestion: Check directory permissions or run with appropriate privileges"
                )
                sys.exit(1)

        except OSError as e:
            logger.error(f"Cannot access data directory: {e}")
            logger.error(
                "Suggestion: Check the path exists and you have permission to access it"
            )
            sys.exit(1)

    @staticmethod
    def _validate_disk_space(data_path: Path, min_gb: float = 2.0) -> None:
        """Validate sufficient disk space is available."""
        try:
            stat = shutil.disk_usage(data_path.parent)
            free_gb = stat.free / (1024**3)

            if free_gb < min_gb:
                logger.error(
                    f"Insufficient disk space. Need {min_gb:.1f}GB, have {free_gb:.1f}GB"
                )
                logger.error(
                    "Suggestion: Free up disk space or use a different data directory"
                )
                sys.exit(1)

        except OSError as e:
            logger.warning(f"Warning: Cannot check disk space: {e}")
            # Continue anyway - disk space check is not critical

    @classmethod
    def create(
        cls,
        backend: str,
        port: int = DEFAULT_PORT,
        workspace: str = DEFAULT_WORKSPACE,
        data_dir: Optional[str] = None,
        bolt_port: Optional[int] = None,
        debug: bool = False,
    ) -> "Config":
        """Create configuration with environment variable overrides."""
        # Apply environment variable overrides
        port = int(os.environ.get("PORT", port))
        workspace = os.environ.get("WORKSPACE", workspace)
        data_dir = os.environ.get("DATA_DIR", data_dir)

        # Validate inputs
        cls._validate_port(port, "port")
        if bolt_port is not None:
            cls._validate_port(bolt_port, "bolt_port")
            if bolt_port == port:
                logger.error(
                    f"bolt_port ({bolt_port}) cannot be the same as port ({port})"
                )
                logger.error(
                    "Suggestion: Use different port numbers or omit --bolt-port"
                )
                sys.exit(1)

        cls._validate_workspace(workspace)

        # Determine data directory
        if data_dir:
            data_path = Path(data_dir).resolve()
        else:
            xdg_data_home = os.environ.get(
                "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
            )
            data_path = Path(xdg_data_home) / "dockerhound" / workspace

        # Validate data directory access and disk space
        cls._validate_data_directory(data_path)
        cls._validate_disk_space(data_path)

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
            debug=debug,
            neo4j_vol=data_path / "neo4j",
            postgres_vol=data_path / "postgres",
            admin_name=admin_name,
            admin_password=admin_password,
            bloodhound_image=bloodhound_image,
        )


class ContainerManager(ABC):
    """Base class for container management."""

    def __init__(self, config: Config, run_command_fn: Callable):
        self.config = config
        self._run_command = run_command_fn
        self.timestamp = str(int(time.time()))

    @abstractmethod
    def get_container_name(self) -> str:
        """Get the container name."""
        pass

    @abstractmethod
    def get_run_command(self) -> List[str]:
        """Get the command to run the container."""
        pass

    @abstractmethod
    def get_ready_log_pattern(self) -> str:
        """Get the log pattern that indicates the container is ready."""
        pass

    @abstractmethod
    def get_error_log_patterns(self) -> List[str]:
        """Get the log patterns that indicate container failure."""
        pass

    def start(self) -> None:
        """Start the container."""
        container_name = self.get_container_name()
        logger.info(f"Running {container_name.lower()} container ...")
        cmd = self.get_run_command()
        self._run_command(cmd)

    def wait_for_ready(self) -> None:
        """Wait for the container to be ready."""
        container_name = self.get_container_name()
        logger.info(f"Wait until {container_name.lower()} is ready ...")

        while True:
            time.sleep(1)
            try:
                result = self._run_command(
                    [
                        self.config.backend,
                        "logs",
                        "--since",
                        self.timestamp,
                        container_name,
                    ],
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    logs = result.stdout
                    if self.get_ready_log_pattern() in logs:
                        break

                    error_patterns = self.get_error_log_patterns()
                    if any(pattern in logs for pattern in error_patterns):
                        logger.error(logs)
                        logger.error(f"{container_name} container failed")
                        sys.exit(1)
                else:
                    #  print(result.stdout)
                    logger.error(result.stderr.strip())
                    logger.error(
                        f"{container_name} container failed with returncode {result.returncode}"
                    )
                    sys.exit(1)
            except Exception:
                continue


class NetworkManager:
    """Manages container networks."""

    def __init__(self, config: Config, run_command_fn: Callable):
        self.config = config
        self._run_command = run_command_fn
        self._created_network = False

    def network_exists(self) -> bool:
        """Check if the network exists."""
        try:
            result = self._run_command(
                [self.config.backend, "network", "exists", self.config.network],
                check=False,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Failed to check network existence: {e}")
            return False

    def setup(self) -> None:
        """Create the container network if it doesn't exist."""
        if not self.network_exists():
            try:
                self._run_command(
                    [self.config.backend, "network", "create", self.config.network]
                )
                self._created_network = True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to create network '{self.config.network}'")
                if "already exists" in str(e).lower():
                    logger.error(
                        f"Suggestion: Network may exist but be inaccessible. Try: {self.config.backend} network rm {self.config.network}"
                    )
                raise

    def cleanup(self) -> None:
        """Clean up the network if we created it."""
        if self._created_network:
            try:
                self._run_command(
                    [self.config.backend, "network", "rm", self.config.network],
                    check=False,
                )
            except Exception:
                pass


class PostgresManager(ContainerManager):
    """Manages PostgreSQL container."""

    def get_container_name(self) -> str:
        return self.config.postgres_container

    def get_run_command(self) -> List[str]:
        return [
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

    def get_ready_log_pattern(self) -> str:
        return "database system is ready to accept connections"

    def get_error_log_patterns(self) -> List[str]:
        return ["FATAL:", "ERROR:", "could not"]

    def set_password_expiry(self) -> None:
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


class Neo4jManager(ContainerManager):
    """Manages Neo4j container."""

    def get_container_name(self) -> str:
        return self.config.neo4j_container

    def get_run_command(self) -> List[str]:
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
                f"NEO4J_AUTH={NEO4J_USER}/{NEO4J_PASSWORD}",
                self.config.neo4j_image,
            ]
        )
        return cmd

    def get_ready_log_pattern(self) -> str:
        return "Remote interface available at http://localhost:7474/"

    def get_error_log_patterns(self) -> List[str]:
        return ["Error"]


class BloodhoundManager(ContainerManager):
    """Manages BloodHound container."""

    def get_container_name(self) -> str:
        return self.config.bloodhound_container

    def get_run_command(self) -> List[str]:
        NEO4J_CONNECTION = f"neo4j://{NEO4J_USER}:{NEO4J_PASSWORD}@graph-db:7687/"
        result = [
            self.config.backend,
            "run",
            "--rm",
            "--replace",
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
            f"bhe_neo4j_connection={NEO4J_CONNECTION}",
            "-e",
            f"bhe_default_admin_principal_name={self.config.admin_name}",
            "-e",
            f"bhe_default_admin_password={self.config.admin_password}",
            self.config.bloodhound_image,
        ]

        if not self.config.debug:
            result.insert(4, "--detach")

        return result

    def get_ready_log_pattern(self) -> str:
        return "Server started successfully"

    def get_error_log_patterns(self) -> List[str]:
        return ['"level":"error"', '"level":"fatal"', "Error: "]

    def attach_for_monitoring(self) -> None:
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
            subprocess.run(
                [self.config.backend, "attach", self.config.bloodhound_container]
            )
        except KeyboardInterrupt:
            pass


class BloodHoundCE:
    def __init__(self, config: Config):
        self.config = config
        self._started_containers: List[str] = []

        # Initialize managers
        self.network_manager = NetworkManager(config, self._run_command)
        self.postgres_manager = PostgresManager(config, self._run_command)
        self.neo4j_manager = Neo4jManager(config, self._run_command)
        self.bloodhound_manager = BloodhoundManager(config, self._run_command)

        # Set up signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def __enter__(self) -> "BloodHoundCE":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit with cleanup."""
        self.cleanup()

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.info("\nStopping containers ...")
        self.cleanup()
        sys.exit(0)

    def cleanup(self) -> None:
        """Clean up all resources."""
        self._stop_containers()
        self.network_manager.cleanup()

    def _run_command(
        self, cmd: list[str], capture_output: bool = False, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a command with the selected backend."""
        try:
            if self.config.debug:
                logger.debug(f"Running command: {' '.join(cmd)}")

            if capture_output:
                # Always capture output when requested (needed for readiness checks)
                result = subprocess.run(
                    cmd, capture_output=True, text=True, check=check
                )
                if self.config.debug and result.stdout:
                    logger.debug(f"Command stdout: {result.stdout}")
                if self.config.debug and result.stderr:
                    logger.debug(f"Command stderr: {result.stderr}")
                return result
            elif self.config.debug:
                # In debug mode, show output but don't capture it
                return subprocess.run(cmd, text=True, check=check)
            else:
                return subprocess.run(cmd, stdout=subprocess.DEVNULL, check=check)
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}")
            if capture_output and e.stderr:
                logger.error(f"{e.stderr}")

            # Provide helpful suggestions for common failures
            if "not found" in str(e).lower() or "no such" in str(e).lower():
                logger.error(f"Suggestion: Check if {cmd[0]} is installed and in PATH")
            elif "permission denied" in str(e).lower():
                logger.error(
                    "Suggestion: Try running with appropriate privileges or check file permissions"
                )
            elif "port" in str(e).lower() and "already" in str(e).lower():
                logger.error(
                    "Suggestion: Use a different port with --port flag or stop the conflicting service"
                )

            raise

    def _container_exists(self, name: str) -> bool:
        """Check if a container exists."""
        try:
            result = self._run_command(
                [self.config.backend, "container", "exists", name], check=False
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Failed to check container existence: {e}")
            return False

    def setup_directories(self) -> None:
        """Create necessary directories."""
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.neo4j_vol.mkdir(parents=True, exist_ok=True)
        self.config.postgres_vol.mkdir(parents=True, exist_ok=True)

    def setup_network(self) -> None:
        """Create the container network if it doesn't exist."""
        self.network_manager.setup()

    def pull_images(self) -> None:
        """Pull all required container images."""
        images = [
            self.config.bloodhound_image,
            self.config.neo4j_image,
            self.config.postgres_image,
        ]
        for image in images:
            logger.info(f"Pulling {image}...")
            self._run_command([self.config.backend, "pull", image])

    def run_postgres(self) -> None:
        """Start the PostgreSQL container."""
        self.postgres_manager.start()
        self._started_containers.append(self.config.postgres_container)

    def run_neo4j(self) -> None:
        """Start the Neo4j container."""
        self.neo4j_manager.start()
        self._started_containers.append(self.config.neo4j_container)

    def run_bloodhound(self) -> None:
        """Start the BloodHound container."""
        self.bloodhound_manager.start()
        self._started_containers.append(self.config.bloodhound_container)

    def wait_for_neo4j(self) -> None:
        """Wait for Neo4j to be ready."""
        self.neo4j_manager.wait_for_ready()

    def wait_for_bloodhound(self) -> None:
        """Wait for BloodHound to be ready."""
        self.bloodhound_manager.wait_for_ready()

    def set_password_expiry(self) -> None:
        """Set the admin password to not expire for a year."""
        self.postgres_manager.set_password_expiry()

    def _stop_containers(self) -> None:
        """Stop all containers."""
        # Stop containers in reverse order of creation, including BloodHound
        containers = [
            self.config.bloodhound_container,
            self.config.neo4j_container,
            self.config.postgres_container,
        ]
        for container in containers:
            if container in self._started_containers:
                try:
                    logger.info(f"Stopping container {container}...")
                    self._run_command(
                        [self.config.backend, "stop", "-i", container], check=False
                    )
                    self._started_containers.remove(container)
                except (subprocess.SubprocessError, FileNotFoundError):
                    # Container may not exist or backend unavailable - continue cleanup
                    pass

    def _cleanup_network(self) -> None:
        """Clean up the created network."""
        try:
            logger.info(f"Removing network {self.config.network}...")
            self._run_command(
                [self.config.backend, "network", "rm", self.config.network], check=False
            )
            self._created_network = False
        except (subprocess.SubprocessError, FileNotFoundError):
            # Network may not exist or backend unavailable - continue cleanup
            pass

    def attach_to_bloodhound(self) -> None:
        """Attach to BloodHound container for monitoring."""
        self.bloodhound_manager.attach_for_monitoring()

    def run(self) -> None:
        """Main execution flow."""
        try:
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
            success_panel = Panel.fit(
                f"[green]Success! BloodHound CE is running[/green]\n\n"
                f"[bold blue]URL:[/bold blue] http://localhost:{self.config.port}\n"
                f"[bold blue]Login:[/bold blue] {self.config.admin_name}/{self.config.admin_password}\n"
                f"[bold blue]Workspace:[/bold blue] {self.config.workspace}\n\n"
                f"[yellow]Press CTRL-C when you're done.[/yellow]",
                title="[bold green]BloodHound CE Ready[/bold green]",
                border_style="green",
            )
            Console().print(success_panel)

            # Attach to container for log monitoring
            self.attach_to_bloodhound()

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            self.cleanup()
            raise


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

    logger.error("Neither podman nor docker found.")
    logger.error("Suggestion: Install one of the following:")
    logger.error("  - Podman: https://podman.io/getting-started/installation")
    logger.error("  - Docker: https://docs.docker.com/get-docker/")
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
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug mode with verbose container output",
)
@click.argument("command", default="run", type=click.Choice(["run", "pull"]))
def main(
    backend: Optional[str],
    port: int,
    workspace: str,
    data_dir: Optional[str],
    bolt_port: Optional[int],
    debug: bool,
    command: str,
) -> None:
    """Single User BloodHound CE - Run BloodHound Community Edition in containers."""

    # Set logging level based on debug flag
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

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
        debug=debug,
    )

    if command == "pull":
        bh = BloodHoundCE(config)
        bh.pull_images()
        return

    # Use context manager for automatic cleanup on failures
    with BloodHoundCE(config) as bh:
        bh.run()


if __name__ == "__main__":
    main()
