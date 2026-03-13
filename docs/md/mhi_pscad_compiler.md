# Module mhi.pscad.compiler

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/compiler.py*

Python Library Documentation: module mhi.pscad.compiler in mhi.pscad

## NAME
    mhi.pscad.compiler - External Compiler Codecs

## CLASSES
    builtins.object
        CompilerCodecs
    builtins.tuple(builtins.object)
        CompilerConfiguration

### class CompilerCodecs(builtins.object)
- **CompilerCodecs(pscad: 'Optional[PSCAD]')**

        Compiler Configuration Coder/Decoder

        Methods defined here:

- **decode_all(self, params: 'Parameters') -> 'Parameters'** -> `Parameters`
            Decode known external compiler parameters to human-readable string

- **encode_all(** -> `Parameters`
            self,
            params: 'Parameters',
            *,
            current: 'Optional[Parameters]' = None
        ) -> 'Parameters'
            Encode compiler parameters from human-readable strings to
            the internal codes used by PSCAD.

            If not all compiler parameters are given, the current parameters
            may be used to ensure a proper configuration is used.

- **encodes(self, params: 'Parameters') -> 'bool'** -> `bool`
            Determine if any compiler parameters are present

            This may be used to determine if compiler configuration encoding
            is necessary.

- **missing_params(self, _params: 'Parameters') -> 'bool'** -> `bool`
            Determine if a complete set of compiler parameters is present.

            This should be used to determine if the current settings need to
            be retrieved before encoding, or if that step may be skipped.

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(cls, pscad: 'Optional[PSCAD]')**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Readonly properties defined here:

        c_codec
            The C/Linker/VisualStudios Codec

        fortran_codec
            The Fortran Codec

        matlab_codec
            The Matlab Codec

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {'_codec': 'Dict[str, FuzzyCodec]'}

### class CompilerConfiguration(builtins.tuple)
- **CompilerConfiguration(**
- **fortran_version: ForwardRef('str'),**
- **c_version: ForwardRef('str'),**
- **matlab_version: ForwardRef('str')**
        )

        A PSCAD Compiler Configuration

        Method resolution order:
            CompilerConfiguration
            builtins.tuple
            builtins.object

        Methods defined here:

- **__getnewargs__(self) from collections.CompilerConfiguration**
            Return self as a plain tuple.  Used by copy and pickle.

- **__replace__ = _replace(self, /, **kwds)**

- **__repr__(self)**
- **Return repr(self).**

- **_asdict(self) from collections.CompilerConfiguration**
            Return a new dict which maps field names to their values.

- **_replace(self, /, **kwds) from collections.CompilerConfiguration**
            Return a new CompilerConfiguration object replacing specified fields with new values

        ----------------------------------------------------------------------
        Class methods defined here:

- **_make(iterable) from collections.CompilerConfiguration**
            Make a new CompilerConfiguration object from a sequence or iterable

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(**
            _cls,
- **fortran_version: ForwardRef('str'),**
- **c_version: ForwardRef('str'),**
- **matlab_version: ForwardRef('str')**
        ) from namedtuple_CompilerConfiguration.CompilerConfiguration
- **Create new instance of CompilerConfiguration(fortran_version, c_version, matlab_version)**

        ----------------------------------------------------------------------
        Data descriptors defined here:

        fortran_version
            Alias for field number 0

        c_version
            Alias for field number 1

        matlab_version
            Alias for field number 2

        ----------------------------------------------------------------------
        Data and other attributes defined here:

- **__annotations__ = {'c_version': ForwardRef('str'), 'fortran_version': ...**

- **__match_args__ = ('fortran_version', 'c_version', 'matlab_version')**

- **__orig_bases__ = (<function NamedTuple>,)**

        _field_defaults = {}

- **_fields = ('fortran_version', 'c_version', 'matlab_version')**

        ----------------------------------------------------------------------

## DATA
    __all__ = ('CompilerConfiguration', 'CompilerCodecs')

## FILE
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/compiler.py
