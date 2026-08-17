import asyncio
from contextlib import ExitStack
import importlib
import math
from numbers import Real
from pathlib import Path
import re
from typing import Any, Mapping, Optional

from .executor import RobustExecutor
from .pscad_config import PscadLaunchConfig, select_installation


_PSOUT_REASON_LIMIT = 256
_PSOUT_DIAGNOSTIC_LIMIT = 128
_PSOUT_CHANNEL_LIMIT = 256


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
        channel: str | None = None,
        summary_only: bool = False,
    ) -> dict:
        if max_samples < 1:
            raise ValueError("max_samples must be positive.")
        return await asyncio.to_thread(
            self._read_psout_sync,
            Path(file_path),
            run_index,
            max_samples,
            channel,
            summary_only,
        )

    def _read_psout_sync(
        self,
        file_path: Path,
        run_index: int,
        max_samples: int,
        channel: str | None,
        summary_only: bool,
    ) -> dict:
        legacy_basename = self._legacy_out_basename(file_path)
        if legacy_basename is not None:
            return self._read_legacy_out_sync(
                file_path,
                legacy_basename,
                run_index,
                max_samples,
                channel,
                summary_only,
            )
        if self.psout_module is None:
            raise RuntimeError(
                "mhi-psout is not installed. Install the Windows extras for PSCAD MCP."
            )
        with self.psout_module.File(str(file_path)) as record:
            if run_index < 0 or run_index >= record.num_runs:
                raise ValueError(
                    f"run_index must be between 0 and {record.num_runs - 1}."
                )
            run = record.run(run_index)
            channels = []
            warnings = []
            skipped_channels = []
            matched = [False]
            self._collect_traces(
                record.root,
                run,
                [],
                channels,
                max_samples,
                warnings,
                skipped_channels,
                channel,
                summary_only,
                matched,
            )
            if channel is not None and not matched[0]:
                selector = str(channel)
                if len(selector) > _PSOUT_REASON_LIMIT:
                    selector = selector[: _PSOUT_REASON_LIMIT - 3] + "..."
                if len(warnings) < _PSOUT_DIAGNOSTIC_LIMIT:
                    warnings.append(
                        f"No PSOUT channel matched selector '{selector}'."
                    )
            return {
                "path": str(file_path),
                "runs": record.num_runs,
                "run_index": run_index,
                "channels": channels,
                "warnings": warnings,
                "skipped_channels": skipped_channels,
            }

    @staticmethod
    def _legacy_out_basename(file_path: Path) -> Path | None:
        if file_path.suffix.casefold() != ".out":
            return None
        match = re.fullmatch(r"(.+)_\d{2}", file_path.stem)
        basename = (
            file_path.with_name(match.group(1))
            if match is not None
            else file_path.with_suffix("")
        )
        return basename if basename.with_suffix(".inf").is_file() else None

    @staticmethod
    def _resolve_legacy_companion(
        output_directory: Path,
        companion: Path,
    ) -> Path:
        resolved_directory = output_directory.resolve(strict=True)
        resolved_companion = companion.resolve(strict=True)
        if resolved_companion.parent != resolved_directory:
            raise ValueError(
                f"Legacy PSCAD companion escapes the output directory: {companion}"
            )
        if not resolved_companion.is_file():
            raise ValueError(
                f"Legacy PSCAD companion is not a file: {companion}"
            )
        return resolved_companion

    def _read_legacy_out_sync(
        self,
        file_path: Path,
        basename: Path,
        run_index: int,
        max_samples: int,
        channel: str | None,
        summary_only: bool,
    ) -> dict:
        if run_index != 0:
            raise ValueError("run_index must be 0 for legacy PSCAD OUT files.")

        primary_output = file_path.resolve(strict=True)
        output_directory = primary_output.parent
        metadata_path = self._resolve_legacy_companion(
            output_directory,
            basename.with_suffix(".inf"),
        )

        metadata = []
        pattern = re.compile(
            r'^PGB\((\d+)\).*?Desc="([^"]+)"\s+Group="([^"]*)"(?:\s+Max=([^\s]+)\s+Min=([^\s]+)\s+Units="([^"]*)")?'
        )
        with metadata_path.open(encoding="utf-8") as stream:
            for line in stream:
                match = pattern.match(line)
                if match is None:
                    continue
                call_id = int(match.group(1))
                description = match.group(2)
                group = match.group(3)
                maximum = minimum = None
                if match.group(4) is not None:
                    try:
                        maximum = float(match.group(4))
                        minimum = float(match.group(5))
                    except ValueError:
                        continue
                    if not math.isfinite(maximum) or not math.isfinite(minimum):
                        continue
                metadata.append(
                    {
                        "call_id": call_id,
                        "description": description,
                        "group": group,
                        "units": match.group(6) or "",
                        "max": maximum,
                        "min": minimum,
                        "path": f"{group}/{description}" if group else description,
                    }
                )
        metadata.sort(key=lambda item: item["call_id"])
        if not metadata:
            raise ValueError(
                f"Legacy PSCAD metadata contains no output channels: {basename}.inf"
            )
        expected = list(range(1, len(metadata) + 1))
        observed = [item["call_id"] for item in metadata]
        if observed != expected:
            raise ValueError("Legacy PSCAD output channel numbers are not sequential.")

        warnings = []
        if channel is not None:
            selected = [
                item
                for item in metadata
                if channel in {item["path"], item["description"]}
            ]
            if not selected:
                selector = channel[:_PSOUT_REASON_LIMIT]
                warnings.append(
                    f"No PSOUT channel matched selector '{selector}'."
                )
        else:
            selected = metadata
        if len(selected) > _PSOUT_CHANNEL_LIMIT:
            warnings.append(
                f"PSOUT channel limit {_PSOUT_CHANNEL_LIMIT} reached."
            )
            selected = selected[:_PSOUT_CHANNEL_LIMIT]

        first_output = self._resolve_legacy_companion(
            output_directory,
            Path(f"{basename}_01.out"),
        )
        with first_output.open(encoding="utf-8") as stream:
            sample_count = sum(1 for line in stream if line.strip())
        step = max(1, (sample_count + max_samples - 1) // max_samples)
        file_count = (
            (max(item["call_id"] for item in selected) + 9) // 10
            if selected
            else 1
        )
        domains = []
        values = {item["call_id"]: [] for item in selected}
        with ExitStack() as stack:
            streams = [
                stack.enter_context(
                    self._resolve_legacy_companion(
                        output_directory,
                        Path(f"{basename}_{index:02d}.out"),
                    ).open(encoding="utf-8")
                )
                for index in range(1, file_count + 1)
            ]
            row_index = 0
            while True:
                rows = []
                for stream in streams:
                    line = stream.readline()
                    while line and not line.strip():
                        line = stream.readline()
                    rows.append(line)
                if not rows[0]:
                    if any(rows[1:]):
                        raise ValueError("Legacy PSCAD output files have different lengths.")
                    break
                if any(not row for row in rows[1:]):
                    raise ValueError("Legacy PSCAD output files have different lengths.")
                if row_index % step == 0 and len(domains) < max_samples:
                    parsed = [[float(value) for value in row.split()] for row in rows]
                    times = [row[0] for row in parsed]
                    if any(value != times[0] for value in times[1:]):
                        raise ValueError("Legacy PSCAD output file time columns differ.")
                    domains.append(times[0])
                    for item in selected:
                        call_id = item["call_id"]
                        file_index = (call_id - 1) // 10
                        column_index = (call_id - 1) % 10 + 1
                        try:
                            values[call_id].append(parsed[file_index][column_index])
                        except IndexError as error:
                            raise ValueError(
                                f"Legacy PSCAD output channel {call_id} is missing data."
                            ) from error
                row_index += 1

        channels = []
        for item in selected:
            payload = {
                "path": item["path"],
                "call_id": item["call_id"],
                "description": item["description"],
                "group": item["group"],
                "units": item["units"],
                "max": item["max"],
                "min": item["min"],
            }
            if summary_only:
                payload["summary"] = self._summarize_samples(
                    values[item["call_id"]]
                )
            else:
                payload["values"] = values[item["call_id"]]
                payload["domain"] = list(domains)
            channels.append(payload)
        return {
            "path": str(file_path),
            "runs": 1,
            "run_index": 0,
            "channels": channels,
            "warnings": warnings,
            "skipped_channels": [],
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
        channel: str | None,
        summary_only: bool,
        matched: list[bool],
    ) -> None:
        try:
            name = node["Name"]
        except Exception as error:
            self._record_psout_skip(
                node,
                path,
                "identify",
                error,
                warnings,
                skipped_channels,
            )
            return
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
            channel_path = "/".join(next_path)
            if channel is not None and channel_path != channel:
                return
            matched[0] = True
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
            if len(channels) >= _PSOUT_CHANNEL_LIMIT:
                if len(warnings) < _PSOUT_DIAGNOSTIC_LIMIT:
                    warnings.append(
                        f"PSOUT channel limit {_PSOUT_CHANNEL_LIMIT} reached."
                    )
                return
            channel_payload = {
                "path": channel_path,
                "call_id": node.id,
            }
            if summary_only:
                channel_payload["summary"] = self._summarize_samples(values)
            else:
                channel_payload["values"] = values
                channel_payload["domain"] = domain
            channels.append(channel_payload)
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
                channel,
                summary_only,
                matched,
            )

    @staticmethod
    def _summarize_samples(values: list) -> dict:
        if not values:
            return {"count": 0, "numeric": False}
        if not all(
            isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in values
        ):
            return {"count": len(values), "numeric": False}
        numeric = [float(value) for value in values]
        return {
            "count": len(numeric),
            "min": min(numeric),
            "max": max(numeric),
            "mean": sum(numeric) / len(numeric),
            "first": numeric[0],
            "last": numeric[-1],
        }

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
