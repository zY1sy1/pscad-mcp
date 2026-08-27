import ast
import importlib.metadata
import importlib.util
import inspect
import logging
import os
import pydoc
import re
import stat
import threading
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, ClassVar

from .. import __version__
from ..core.backend.base import BackendError

logger = logging.getLogger("pscad-mcp.doc_manager")

class SourceAnalyzer:
    """
    Parses Python source files using AST to extract metadata 
    that pydoc might miss (decorators like @rmi, type hints, etc.)
    """
    def __init__(self, file_path: str | os.PathLike[str]):
        self.file_path = Path(file_path)
        self.classes = {}
        self.functions = {}
        self._analyze()

    def _analyze(self):
        if not self.file_path.exists():
            return
            
        try:
            tree = ast.parse(self.file_path.read_text(encoding="utf-8"))
                
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    self.classes[node.name] = self._parse_class(node)
                elif isinstance(node, ast.FunctionDef):
                    self.functions[node.name] = self._parse_function(node)
        except Exception as error:
            logger.error(
                "Source analysis failed after %s.",
                type(error).__name__,
            )

    def _parse_class(self, node: ast.ClassDef) -> dict[str, Any]:
        methods = {}
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                methods[item.name] = self._parse_function(item)
        return {
            "name": node.name,
            "methods": methods,
            "bases": [ast.dump(b) for b in node.bases]
        }

    def _parse_function(self, node: ast.FunctionDef) -> dict[str, Any]:
        decorators = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                decorators.append(d.id)
            elif isinstance(d, ast.Call) and isinstance(d.func, ast.Name):
                decorators.append(d.func.id)
            elif isinstance(d, ast.Attribute) and isinstance(d.attr, str):
                decorators.append(d.attr)
        
        # Extract basic type hints from arguments if available
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args.append(arg_str)
            
        return {
            "name": node.name,
            "decorators": decorators,
            "args": args,
            "returns": ast.unparse(node.returns) if node.returns else None
        }

class DocumentationManager:
    """
    Handles extraction and synchronization of mhi-pscad documentation.
    Produces LLM-friendly Markdown output enriched with source analysis.
    """
    MODULES: ClassVar[tuple[str, ...]] = (
        "mhi.pscad", 
        "mhi.pscad.project", 
        "mhi.pscad.canvas", 
        "mhi.pscad.component",
        "mhi.pscad.types",
        "mhi.pscad.definition",
        "mhi.pscad.control",
        "mhi.pscad.remote",
        "mhi.pscad.simset",
        "mhi.pscad.compiler",
        "mhi.pscad.graph",
        "mhi.pscad.instrument",
        "mhi.pscad.graphics",
        "mhi.pscad.parameter_grid",
        "mhi.pscad.resource",
        "mhi.pscad.unit",
        "mhi.pscad.wizard",
        "mhi.pscad.form",
        "mhi.pscad.certificate",
        "mhi.pscad.annotation",
    )

    SETTING = "PSCAD_MCP_DOCUMENTATION_DIR"
    _SYNC_LOCKS: ClassVar[dict[Path, threading.RLock]] = {}
    _SYNC_LOCKS_GUARD: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        docs_dir: str | os.PathLike[str],
        *,
        issue: str | None = None,
    ):
        self.base_dir = Path(docs_dir).expanduser().resolve()
        self.md_dir = self.base_dir / "md"
        self.raw_dir = self.base_dir / "raw"
        self.issue = issue

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "DocumentationManager":
        if cls.SETTING in environ:
            override = environ.get(cls.SETTING)
            if type(override) is str:
                normalized = str.strip(override)
                try:
                    candidate = Path(normalized)
                    if normalized and candidate.is_absolute():
                        return cls(candidate)
                except (OSError, ValueError):
                    pass
            return cls(cls._default_root(environ), issue=cls.SETTING)

        return cls(cls._default_root(environ))

    @staticmethod
    def _default_root(environ: Mapping[str, str]) -> Path:
        local_app_data = environ.get("LOCALAPPDATA")
        if type(local_app_data) is str:
            normalized = str.strip(local_app_data)
            try:
                candidate = Path(normalized)
                if normalized and candidate.is_absolute():
                    return candidate / "pscad-mcp" / "docs"
            except (OSError, ValueError):
                pass
        return Path.home() / ".local" / "state" / "pscad-mcp" / "docs"

    def raise_for_issue(self, operation: str) -> None:
        if self.issue is None:
            return
        raise BackendError(
            "DOCUMENTATION_CONFIG_INVALID",
            "The documentation storage configuration is invalid.",
            "server",
            operation,
            {"setting": self.issue},
        )

    @staticmethod
    def _package_version() -> str:
        try:
            return importlib.metadata.version("pscad-mcp")
        except importlib.metadata.PackageNotFoundError:
            return __version__

    @classmethod
    def _sync_lock_for(cls, base_dir: Path) -> threading.RLock:
        with cls._SYNC_LOCKS_GUARD:
            lock = cls._SYNC_LOCKS.get(base_dir)
            if lock is None:
                lock = threading.RLock()
                cls._SYNC_LOCKS[base_dir] = lock
            return lock

    @staticmethod
    def storage_error(operation: str, directory: str) -> BackendError:
        safe_operation = (
            operation
            if operation
            in {
                "sync_documentation",
                "list_documentation",
                "read_documentation",
            }
            else "documentation"
        )
        safe_directory = directory if directory in {"md", "raw"} else "generated"
        return BackendError(
            "DOCUMENTATION_STORAGE_INVALID",
            "The documentation storage boundary is invalid.",
            "server",
            safe_operation,
            {"directory": safe_directory},
        )

    @classmethod
    def _storage_error(cls, directory: str) -> BackendError:
        return cls.storage_error("sync_documentation", directory)

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        metadata = path.lstat()
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)

    @classmethod
    def _validate_storage_directory(
        cls,
        base_dir: Path,
        directory: Path,
        *,
        operation: str = "sync_documentation",
    ) -> None:
        label = directory.name if directory.name in {"md", "raw"} else "generated"
        try:
            if directory != base_dir / label or directory.parent != base_dir:
                raise cls.storage_error(operation, label)
            if (
                directory.is_symlink()
                or cls._is_reparse_point(directory)
                or not directory.is_dir()
            ):
                raise cls.storage_error(operation, label)
            if (
                base_dir.is_symlink()
                or cls._is_reparse_point(base_dir)
                or not base_dir.is_dir()
            ):
                raise cls.storage_error(operation, label)
            resolved_base = base_dir.resolve(strict=True)
            resolved_directory = directory.resolve(strict=True)
            if (
                resolved_base != base_dir
                or resolved_directory != directory
                or resolved_directory.parent != resolved_base
            ):
                raise cls.storage_error(operation, label)
        except BackendError:
            raise
        except Exception as error:
            logger.error(
                "Documentation storage validation for %s failed after %s.",
                label,
                type(error).__name__,
            )
            raise cls.storage_error(operation, label) from None

    def validate_read_directory(self, operation: str) -> bool:
        self.raise_for_issue(operation)
        try:
            self.md_dir.lstat()
        except FileNotFoundError:
            return False
        except Exception:
            raise self.storage_error(operation, "md") from None
        self._validate_storage_directory(
            self.base_dir,
            self.md_dir,
            operation=operation,
        )
        return True

    def validate_read_target(self, target: Path, operation: str) -> Path:
        if not self.validate_read_directory(operation):
            raise FileNotFoundError from None
        candidate = Path(target)
        try:
            if candidate.parent != self.md_dir:
                raise self.storage_error(operation, "md")
            candidate.lstat()
            if (
                candidate.is_symlink()
                or self._is_reparse_point(candidate)
                or not candidate.is_file()
                or candidate.resolve(strict=True).parent != self.md_dir
            ):
                raise self.storage_error(operation, "md")
        except FileNotFoundError:
            raise
        except BackendError:
            raise
        except Exception:
            raise self.storage_error(operation, "md") from None
        if not self.validate_read_directory(operation):
            raise FileNotFoundError from None
        return candidate

    @classmethod
    def _validate_storage_target(
        cls,
        base_dir: Path,
        destination: Path,
    ) -> None:
        parent = destination.parent
        cls._validate_storage_directory(base_dir, parent)
        try:
            if destination.is_symlink() or (
                destination.exists() and cls._is_reparse_point(destination)
            ):
                raise cls._storage_error(parent.name)
        except BackendError:
            raise
        except Exception as error:
            logger.error(
                "Documentation destination validation for %s failed after %s.",
                parent.name,
                type(error).__name__,
            )
            raise cls._storage_error(parent.name) from None

    @classmethod
    def _validate_temporary_file(
        cls,
        temporary_path: Path,
        destination_parent: Path,
    ) -> None:
        try:
            if (
                temporary_path.is_symlink()
                or cls._is_reparse_point(temporary_path)
                or not temporary_path.is_file()
                or temporary_path.resolve(strict=True).parent != destination_parent
            ):
                raise cls._storage_error(destination_parent.name)
        except BackendError:
            raise
        except Exception as error:
            logger.error(
                "Documentation temporary-file validation for %s failed after %s.",
                destination_parent.name,
                type(error).__name__,
            )
            raise cls._storage_error(destination_parent.name) from None

    def _prepare_storage(self) -> None:
        for directory in (self.md_dir, self.raw_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self._validate_storage_directory(self.base_dir, directory)
            except BackendError:
                raise
            except Exception as error:
                logger.error(
                    "Documentation storage preparation for %s failed after %s.",
                    directory.name,
                    type(error).__name__,
                )
                raise self._storage_error(directory.name) from None

    @classmethod
    def _atomic_write(
        cls,
        target: Path,
        content: str,
        *,
        base_dir: Path | None = None,
    ) -> None:
        destination = Path(target)
        temporary_path: Path | None = None
        try:
            if base_dir is not None:
                cls._validate_storage_target(base_dir, destination)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            if base_dir is not None:
                cls._validate_storage_target(base_dir, destination)
                cls._validate_temporary_file(
                    temporary_path,
                    destination.parent,
                )
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def sync(self) -> list[str]:
        """Synchronize reference files from the installed mhi-pscad library."""
        self.raise_for_issue("sync_documentation")
        with self._sync_lock_for(self.base_dir):
            return self._sync_locked()

    def _sync_locked(self) -> list[str]:
        self._prepare_storage()
        results = []
        for mod_name in self.MODULES:
            try:
                # 1. Find source file
                spec = importlib.util.find_spec(mod_name)
                source_file = spec.origin if spec else None
                
                analyzer = None
                if source_file and source_file.endswith(".py"):
                    analyzer = SourceAnalyzer(source_file)

                # 2. Get raw output via pydoc
                try:
                    raw_doc = pydoc.render_doc(mod_name, renderer=pydoc.plaintext)
                except Exception as error:
                    logger.warning(
                        "pydoc failed for %s after %s; using manual inspection.",
                        mod_name,
                        type(error).__name__,
                    )
                    raw_doc = self._manual_inspect_raw(mod_name)
                
                raw_path = self.raw_dir / f"{mod_name.replace('.', '_')}.txt"
                self._atomic_write(raw_path, raw_doc, base_dir=self.base_dir)

                # 3. Process into enriched markdown
                enriched_md = self._extract_enriched_markdown(mod_name, raw_doc, analyzer)
                md_path = self.md_dir / f"{mod_name.replace('.', '_')}.md"
                self._atomic_write(md_path, enriched_md, base_dir=self.base_dir)

                results.append(f"Synced {mod_name} (Enriched)")
            except BackendError:
                raise
            except Exception as error:
                logger.error(
                    "Failed to sync %s after %s.",
                    mod_name,
                    type(error).__name__,
                )
                results.append(f"Failed {mod_name}: {type(error).__name__}")
        return results

    def _clean_pydoc(self, text: str) -> str:
        """Remove overstriking and other pydoc artifacts."""
        text = re.sub(r'(.)\x08\1', r'\1', text)
        text = re.sub(r'.\x08', '', text)
        return text

    def _extract_enriched_markdown(
        self,
        mod_name: str,
        raw_doc: str,
        analyzer: SourceAnalyzer | None,
    ) -> str:
        """Process raw pydoc text and enrich with AST analysis."""
        clean_doc = self._clean_pydoc(raw_doc)
        lines = clean_doc.splitlines()
        md_lines = [
            f"# Module {mod_name} (pscad-mcp {self._package_version()})\n"
        ]

        skip_inheritance_for = {
            "builtins.object", "builtins.int", "builtins.tuple", 
            "enum.Enum", "enum.IntEnum", "enum.ReprEnum", "enum.EnumType"
        }
        
        in_file_section = False
        in_skipped_inheritance = False
        current_class = None
        
        for line in lines:
            stripped = line.strip()
            is_top_level_heading = (
                bool(stripped)
                and not line[:1].isspace()
                and stripped.isupper()
            )

            if in_file_section:
                if not is_top_level_heading:
                    continue
                in_file_section = False

            if is_top_level_heading and stripped == "FILE":
                in_file_section = True
                continue

            if not stripped:
                md_lines.append("")
                continue
            
            if is_top_level_heading:
                md_lines.append(f"## {stripped}")
                continue
            
            if "Methods inherited from" in line or "Data descriptors inherited from" in line:
                if any(noise in line for noise in skip_inheritance_for):
                    in_skipped_inheritance = True
                    continue
                else:
                    in_skipped_inheritance = False
            
            if in_skipped_inheritance and not line.startswith("     |"):
                in_skipped_inheritance = False

            if in_skipped_inheritance:
                continue

            # Class identification
            if line.startswith("    class "):
                md_lines.append(f"### {stripped}")
                # Try to find class name to start tracking methods
                match = re.search(r'class (\w+)', stripped)
                if match:
                    current_class = match.group(1)
                continue

            # Method/Function identification
            is_method = line.startswith("    def ") or (line.startswith("     |  ") and "(" in line)
            if is_method:
                clean_meth = stripped.replace("|", "").strip()
                # Try to extract method name
                meth_match = re.search(r'(\w+)\s*\(', clean_meth)
                
                meta_info = ""
                if meth_match:
                    meth_name = meth_match.group(1)
                    # Enrichment logic
                    if current_class and analyzer and current_class in analyzer.classes:
                        cls_meta = analyzer.classes[current_class]
                        if meth_name in cls_meta["methods"]:
                            func_meta = cls_meta["methods"][meth_name]
                            # Add decorators
                            if func_meta["decorators"]:
                                tags = [f"`@{d}`" for d in func_meta["decorators"]]
                                meta_info += " " + " ".join(tags)
                            # Add type hints if pydoc lacks them
                            if func_meta["returns"]:
                                meta_info += f" -> `{func_meta['returns']}`"
                    elif analyzer and meth_name in analyzer.functions:
                        func_meta = analyzer.functions[meth_name]
                        if func_meta["decorators"]:
                            tags = [f"`@{d}`" for d in func_meta["decorators"]]
                            meta_info += " " + " ".join(tags)

                md_lines.append(f"- **{clean_meth}**{meta_info}")
            else:
                md_lines.append(line.replace("|", " ").rstrip())
        
        return "\n".join(md_lines)

    def _manual_inspect_raw(self, mod_name: str) -> str:
        """Fallback crude raw doc generation."""
        import importlib
        try:
            mod = importlib.import_module(mod_name)
            output = [f"MANUAL INSPECTION FOR {mod_name}\n"]
            # Add module docstring
            if mod.__doc__:
                output.append(f"{mod.__doc__}\n")
                
            for name, obj in inspect.getmembers(mod):
                if not name.startswith('_'):
                    doc = getattr(obj, "__doc__", "No docstring")
                    output.append(f"\n--- {name} ---\n{doc}\n")
            return "\n".join(output)
        except Exception as error:
            return f"MANUAL_INSPECTION_FAILED: {type(error).__name__}"

# Shared instance. Path resolution is intentionally lazy and performs no writes.
doc_manager = DocumentationManager.from_environ(os.environ)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print("🚀 Starting Rich Enriched PSCAD Documentation Sync...")
    results = doc_manager.sync()
    for res in results:
        print(f"  {res}")
    print("✅ Sync Complete.")
