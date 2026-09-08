"""Names and membership of one PSCAD output dataset."""

import re
from pathlib import Path

_NUMBERED = re.compile(r"(?P<base>.+)_(?P<index>\d{2,})$")


def legacy_output_stem(selected: Path) -> str:
    match = _NUMBERED.fullmatch(selected.stem)
    return match.group("base") if match else selected.stem


def output_dataset_parts(selected: Path) -> set[Path]:
    if selected.suffix.casefold() != ".out":
        return {selected.absolute()}
    stem = legacy_output_stem(selected).casefold()
    return {
        path.absolute()
        for path in selected.parent.iterdir()
        if path.suffix.casefold() == ".out"
        and (path.stem.casefold() == stem or legacy_output_stem(path).casefold() == stem)
    }
