# CI Schema Metadata Compatibility Design

## Problem

The `main` branch Windows CI fails only on Python 3.10. The contract test
`test_complex_inputs_have_model_facing_shape_examples` raises `KeyError:
'description'` while inspecting descriptions for complex tool arguments. The
same commit passes on Python 3.11 through 3.14.

FastMCP builds each tool's argument model from the registered callable. On
Python 3.10, the FastMCP/Pydantic metadata merge can omit descriptions carried
by the original `typing.Annotated` parameter annotations. The registration
layer currently relies on the generated model or on re-inspecting the wrapped
callable, so it does not have a stable cross-version source for those
descriptions.

## Chosen Design

Resolve parameter annotations once in `register_tool`, before FastMCP sees the
wrapper, and derive a mapping of parameter names to `Annotated` descriptions.
Pass that mapping into `_register_with_original_result`. During schema repair,
use the generated argument model's field description when present, then the
explicit original-annotation mapping, then the existing wrapper annotation
fallback. Only missing schema descriptions are filled, preserving any metadata
FastMCP already generated.

This keeps the compatibility behavior inside the registration boundary, avoids
version-specific assumptions about FastMCP internals, and leaves tool
signatures, business behavior, and the CI matrix unchanged.

## Testing

Add a focused registration test that exercises schema repair when the generated
model field has no description and the wrapper signature has no usable
annotation metadata, while an explicit original-annotation mapping is
available. Keep the existing model-facing shape test as the end-to-end
contract. Run the focused tests, the full pytest suite, Ruff's CI selection,
package verification, compile checks, dependency checks, and the 97-tool
inventory assertion.

## Alternatives Considered

1. Relax the contract test to use `schema.get("description")`. Rejected because
   it would hide a real model-facing metadata regression.
2. Hard-code descriptions in the registration layer or catalog. Rejected
   because it duplicates tool annotations and can drift from the function API.
3. Depend only on `arg_model.model_fields` or only on the wrapper signature.
   Rejected because either source is affected by the cross-version metadata
   behavior observed in CI.
