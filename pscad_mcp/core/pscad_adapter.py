import asyncio
import importlib
from pathlib import Path
from typing import Any, Mapping, Optional

from .executor import RobustExecutor
from .pscad_config import PscadLaunchConfig, select_installation


_PSOUT_REASON_LIMIT = 256
_PSOUT_DIAGNOSTIC_LIMIT = 128


class PscadAdapter:
    """Version-sensitive boundary around the MHI PSCAD and PSOUT APIs."""

    def __init__(
        self,
        executor: RobustExecutor,
        *,
        pscad_module: Any = None,
        psout_module: Any = None,
        environ: Optional[Mapping[str, str]] = None,
    ):
        self.executor = executor
        self.pscad_module = (
            pscad_module if pscad_module is not None else self._optional_import("mhi.pscad")
        )
        self.psout_module = (
            psout_module if psout_module is not None else self._optional_import("mhi.psout")
        )
        self.config = PscadLaunchConfig.from_environ(environ)
        self._pscad = None
        self.owns_process = False
        self.selected_installation: Optional[tuple[str, bool]] = None

    @staticmethod
    def _optional_import(module_name: str) -> Any:
        try:
            return importlib.import_module(module_name)
        except ImportError:
            return None

    @property
    def pscad(self) -> Any:
        if self._pscad is None:
            raise RuntimeError("PSCAD is not connected. Call get_local_pscad first.")
        return self._pscad

    async def attach_local(self) -> Any:
        if self.pscad_module is None:
            raise RuntimeError(
                "mhi-pscad is not installed. Install the Windows extras for PSCAD MCP."
            )

        self._pscad = None
        self.owns_process = False
        self.selected_installation = None

        if self.config.version is None and self.config.x64 is None:
            try:
                self._pscad = await self.executor.run_safe(
                    self.pscad_module.connect
                )
                return self._pscad
            except (ProcessLookupError, ConnectionError):
                pass

        installations = await self.executor.run_safe(self.pscad_module.versions)
        version, x64 = select_installation(installations, self.config)

        def launch_selected() -> Any:
            return self.pscad_module.launch(
                version=version,
                x64=x64,
                minimum=version,
                timeout=self.config.timeout,
            )

        self._pscad = await self.executor.run_safe(
            launch_selected,
            timeout=self.config.timeout + 5,
        )
        self.owns_process = True
        self.selected_installation = (version, x64)
        return self._pscad

    def disconnect(self) -> None:
        self._pscad = None
        self.owns_process = False
        self.selected_installation = None

    async def heartbeat(self) -> dict:
        pscad = self.pscad
        alive = await self.call(pscad, "is_alive")
        busy = await self.call(pscad, "is_busy")
        return {"alive": bool(alive), "busy": bool(busy)}

    async def call(
        self,
        target: Any,
        method_name: str,
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        method = getattr(target, method_name)
        return await self.executor.run_safe(
            method, *args, timeout=timeout, **kwargs
        )

    async def projects(self) -> Any:
        return await self.call(self.pscad, "projects")

    async def project(self, project_name: str) -> Any:
        return await self.call(self.pscad, "project", project_name)

    async def project_definitions(self, project_name: str) -> list[str]:
        project = await self.project(project_name)
        definitions = await self.call(project, "definitions")
        return [str(item) for item in definitions]

    async def simulation_set_names(self) -> list[str]:
        names = await self.call(self.pscad, "simulation_sets")
        return [str(name) for name in names]

    async def simulation_set(self, set_name: str) -> Any:
        return await self.call(self.pscad, "simulation_set", set_name)

    async def settings(self, values: Optional[dict] = None) -> Any:
        if values is None:
            return await self.call(self.pscad, "settings")
        return await self.call(self.pscad, "settings", **values)

    async def read_psout(
        self,
        file_path: str,
        *,
        run_index: int = 0,
        max_samples: int = 10_000,
    ) -> dict:
        if self.psout_module is None:
            raise RuntimeError(
                "mhi-psout is not installed. Install the Windows extras for PSCAD MCP."
            )
        if max_samples < 1:
            raise ValueError("max_samples must be positive.")
        return await asyncio.to_thread(
            self._read_psout_sync,
            Path(file_path),
            run_index,
            max_samples,
        )

    def _read_psout_sync(
        self,
        file_path: Path,
        run_index: int,
        max_samples: int,
    ) -> dict:
        with self.psout_module.File(str(file_path)) as record:
            if run_index < 0 or run_index >= record.num_runs:
                raise ValueError(
                    f"run_index must be between 0 and {record.num_runs - 1}."
                )
            run = record.run(run_index)
            channels = []
            warnings = []
            skipped_channels = []
            self._collect_traces(
                record.root,
                run,
                [],
                channels,
                max_samples,
                warnings,
                skipped_channels,
            )
            return {
                "path": str(file_path),
                "runs": record.num_runs,
                "run_index": run_index,
                "channels": channels,
                "warnings": warnings,
                "skipped_channels": skipped_channels,
            }

    def _collect_traces(
        self,
        node: Any,
        run: Any,
        path: list[str],
        channels: list[dict],
        max_samples: int,
        warnings: list[str],
        skipped_channels: list[dict],
    ) -> None:
        try:
            name = node["Name"]
        except Exception:
            name = None
        next_path = path + ([str(name)] if name else [])
        try:
            children = list(node.calls())
        except Exception as error:
            self._record_psout_skip(
                node,
                next_path,
                "identify",
                error,
                warnings,
                skipped_channels,
            )
            return
        if not children:
            try:
                trace = run.trace(node)
            except Exception as error:
                self._record_psout_skip(
                    node,
                    next_path,
                    "trace",
                    error,
                    warnings,
                    skipped_channels,
                )
                return
            try:
                values = self._sample(trace.data, max_samples)
            except Exception as error:
                self._record_psout_skip(
                    node,
                    next_path,
                    "values",
                    error,
                    warnings,
                    skipped_channels,
                )
                return
            try:
                domain_trace = trace.domain
                domain = (
                    self._sample(domain_trace.data, max_samples)
                    if domain_trace is not None
                    else []
                )
            except Exception as error:
                domain = []
                self._record_psout_skip(
                    node,
                    next_path,
                    "domain",
                    error,
                    warnings,
                    skipped_channels,
                )
            channels.append(
                {
                    "path": "/".join(next_path),
                    "call_id": node.id,
                    "values": values,
                    "domain": domain,
                }
            )
            return
        for child in children:
            self._collect_traces(
                child,
                run,
                next_path,
                channels,
                max_samples,
                warnings,
                skipped_channels,
            )

    @staticmethod
    def _bounded_psout_reason(error: BaseException) -> str:
        value = f"{type(error).__name__}: {error}"
        if len(value) <= _PSOUT_REASON_LIMIT:
            return value
        return value[: _PSOUT_REASON_LIMIT - 3] + "..."

    @staticmethod
    def _record_psout_skip(
        node: Any,
        path: list[str],
        stage: str,
        error: BaseException,
        warnings: list[str],
        skipped_channels: list[dict],
    ) -> None:
        if len(skipped_channels) >= _PSOUT_DIAGNOSTIC_LIMIT:
            return
        try:
            call_id = node.id
        except Exception:
            call_id = None
        try:
            call_id = int(call_id) if call_id is not None else None
        except (TypeError, ValueError, OverflowError):
            call_id = None
        channel_path = "/".join(path)
        reason = PscadAdapter._bounded_psout_reason(error)
        skipped_channels.append(
            {
                "path": channel_path,
                "call_id": call_id,
                "stage": stage,
                "reason": reason,
            }
        )
        if len(warnings) < _PSOUT_DIAGNOSTIC_LIMIT:
            label = channel_path or "<unknown>"
            warnings.append(f"Skipped channel {label} during {stage}: {reason}")

    @staticmethod
    def _sample(values: Any, max_samples: int) -> list:
        values = list(values)
        if len(values) <= max_samples:
            return values
        step = max(1, (len(values) + max_samples - 1) // max_samples)
        return values[::step][:max_samples]
