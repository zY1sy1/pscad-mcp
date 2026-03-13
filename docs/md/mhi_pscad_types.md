# Module mhi.pscad.types

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/types.py*

Python Library Documentation: module mhi.pscad.types in mhi.pscad

## NAME
    mhi.pscad.types

## DESCRIPTION
    =========
    Types
    =========

## CLASSES
    builtins.tuple(builtins.object)
        Message
        Point
        Port
        Rect
        Size
    enum.Enum(builtins.object)
        ContentType
        HelpMode
        Intent
    enum.IntEnum(builtins.int, enum.ReprEnum)
        Align
        Electrical
        FillStyle
        LineStyle
        LookIn
        NodeType
        ProjectType
        Side
        Signal
        View

### class Align(enum.IntEnum)
- **Align(*values)**

        Text Alignment

        Method resolution order:
            Align
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        CENTER = <Align.CENTER: 1>

        LEFT = <Align.LEFT: 0>

        RIGHT = <Align.RIGHT: 2>

        ----------------------------------------------------------------------

### class ContentType(enum.Enum)
- **ContentType(*values)**

        Content type

        .. versionadded:: 3.0.9

        Method resolution order:
            ContentType
            enum.Enum
            builtins.object

        Data and other attributes defined here:

        CONSTANT = <ContentType.CONSTANT: 'Constant'>

        LITERAL = <ContentType.LITERAL: 'Literal'>

        VARIABLE = <ContentType.VARIABLE: 'Variable'>

        ----------------------------------------------------------------------

### class Electrical(enum.IntEnum)
- **Electrical(*values)**

        Electrical Node Types

        Method resolution order:
            Electrical
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        FIXED = <Electrical.FIXED: 0>

        GROUND = <Electrical.GROUND: 3>

        REMOVABLE = <Electrical.REMOVABLE: 1>

        SWITCHED = <Electrical.SWITCHED: 2>

        ----------------------------------------------------------------------

### class FillStyle(enum.IntEnum)
- **FillStyle(*values)**

        Fill Styles

        Method resolution order:
            FillStyle
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        BACKWARD_DIAGONAL = <FillStyle.BACKWARD_DIAGONAL: 2>

        CROSS = <FillStyle.CROSS: 4>

        DIAGONAL_CROSS = <FillStyle.DIAGONAL_CROSS: 5>

        FORWARD_DIAGONAL = <FillStyle.FORWARD_DIAGONAL: 3>

        GRADIENT_BACK_DIAG = <FillStyle.GRADIENT_BACK_DIAG: 10>

        GRADIENT_FORE_DIAG = <FillStyle.GRADIENT_FORE_DIAG: 11>

        GRADIENT_HORZ = <FillStyle.GRADIENT_HORZ: 8>

        GRADIENT_RADIAL = <FillStyle.GRADIENT_RADIAL: 12>

        GRADIENT_VERT = <FillStyle.GRADIENT_VERT: 9>

        HOLLOW = <FillStyle.HOLLOW: 0>

        HORIZONTAL = <FillStyle.HORIZONTAL: 6>

        SOLID = <FillStyle.SOLID: 1>

        VERTICAL = <FillStyle.VERTICAL: 7>

        ----------------------------------------------------------------------

### class HelpMode(enum.Enum)
- **HelpMode(*values)**

        Help mode

        .. versionadded:: 3.0.9

        Method resolution order:
            HelpMode
            enum.Enum
            builtins.object

        Data and other attributes defined here:

        APPEND = <HelpMode.APPEND: 'Append'>

        OVERWRITE = <HelpMode.OVERWRITE: 'Overwrite'>

        ----------------------------------------------------------------------

### class Intent(enum.Enum)
- **Intent(*values)**

        Parameter intent

        .. versionadded:: 3.0.9

        Method resolution order:
            Intent
            enum.Enum
            builtins.object

        Data and other attributes defined here:

        INPUT = <Intent.INPUT: 'Input'>

        OUTPUT = <Intent.OUTPUT: 'Output'>

        ----------------------------------------------------------------------

### class LineStyle(enum.IntEnum)
- **LineStyle(*values)**

        Line Styles

        Method resolution order:
            LineStyle
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        DASH = <LineStyle.DASH: 1>

        DASHDOT = <LineStyle.DASHDOT: 3>

        DOT = <LineStyle.DOT: 2>

        SOLID = <LineStyle.SOLID: 0>

        ----------------------------------------------------------------------

### class LookIn(enum.IntEnum)
- **LookIn(*values)**

        Look In - for search

        Method resolution order:
            LookIn
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        MODULE = <LookIn.MODULE: 0>

        PROJECT = <LookIn.PROJECT: 1>

        WORKSPACE = <LookIn.WORKSPACE: 2>

        WORKSPACE_NO_MASTER_LIBRARY = <LookIn.WORKSPACE_NO_MASTER_LIBRARY: 3>

        ----------------------------------------------------------------------

### class Message(builtins.tuple)
- **Message(**
            text: str,
            label: str,
            status: str,
            scope: str,
            name: str,
            link: int,
            group: int,
            classid: str
        )

- **Message(text, label, status, scope, name, link, group, classid)**

        Method resolution order:
            Message
            builtins.tuple
            builtins.object

        Methods defined here:

- **__getnewargs__(self) from collections.Message**
            Return self as a plain tuple.  Used by copy and pickle.

- **__replace__ = _replace(self, /, **kwds)**

- **__repr__(self) from collections.Message**
            Return a nicely formatted representation string

- **_asdict(self) from collections.Message**
            Return a new dict which maps field names to their values.

- **_replace(self, /, **kwds) from collections.Message**
            Return a new Message object replacing specified fields with new values

        ----------------------------------------------------------------------
        Class methods defined here:

- **_make(iterable) from collections.Message**
            Make a new Message object from a sequence or iterable

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(**
            _cls,
            text: str,
            label: str,
            status: str,
            scope: str,
            name: str,
            link: int,
            group: int,
            classid: str
        ) from namedtuple_Message.Message
- **Create new instance of Message(text, label, status, scope, name, link, group, classid)**

        ----------------------------------------------------------------------
        Data descriptors defined here:

        text
            Alias for field number 0

        label
            Alias for field number 1

        status
            Alias for field number 2

        scope
            Alias for field number 3

        name
            Alias for field number 4

        link
            Alias for field number 5

        group
            Alias for field number 6

        classid
            Alias for field number 7

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {'classid': <class 'str'>, 'group': <class 'int'>, '...

- **__match_args__ = ('text', 'label', 'status', 'scope', 'name', 'link', ...**

- **__orig_bases__ = (<function NamedTuple>,)**

        _field_defaults = {}

- **_fields = ('text', 'label', 'status', 'scope', 'name', 'link', 'group'...**

        ----------------------------------------------------------------------

### class NodeType(enum.IntEnum)
- **NodeType(*values)**

        Node Input/Output/Electrical Type

        Method resolution order:
            NodeType
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        ELECTRICAL = <NodeType.ELECTRICAL: 3>

        INPUT = <NodeType.INPUT: 1>

        OUTPUT = <NodeType.OUTPUT: 2>

        SHORT = <NodeType.SHORT: 4>

        UNKNOWN = <NodeType.UNKNOWN: 0>

        ----------------------------------------------------------------------

### class Point(builtins.tuple)
- **Point(x: ForwardRef('int'), y: ForwardRef('int'))**

        Point class that supports Euclidean distance calculation.

        Examples
        ---------
- **>>> Point(10, 20) + Point(5, 7)**
- **Point(x=15, y=27)**

            It also works with tuple coordinates.

- **>>> p = Point(4, 6) - (2, 3)**
            >>> p.x, p.y
- **(2, 3)**


        .. versionchanged:: 2.9.6
            Now support addition, substraction, and calculation of Euclidian
            distance between points.

        Method resolution order:
            Point
            builtins.tuple
            builtins.object

        Methods defined here:

- **__add__(self, other) -> 'Point'** -> `Point`
            Return self+value.

- **__getnewargs__(self) from collections.Point**
            Return self as a plain tuple.  Used by copy and pickle.

- **__replace__ = _replace(self, /, **kwds)**

- **__repr__(self) from collections.Point**
            Return a nicely formatted representation string

- **__sub__(self, other) -> 'Point'** -> `Point`

- **_asdict(self) from collections.Point**
            Return a new dict which maps field names to their values.

- **_replace(self, /, **kwds) from collections.Point**
            Return a new Point object replacing specified fields with new values

- **distance(self, other: "Union[Tuple[int, int], 'Point']") -> 'float'** -> `float`
            Measures the Euclidean distance to a given point.

            Parameters
            ----------
            other: Union[Tuple[int, int], Point]
                The point to which the Euclidean distance is measured.

            Returns
            -------
            float
                Euclidean Distance


            Examples
            --------
- **>>> p1 = Point(10, 10)**
- **>>> p2 = Point(13, 14)**
- **>>> p1.distance(p2)** -> `float`
                5.0

            .. versionadded:: 2.9.6

        ----------------------------------------------------------------------
        Class methods defined here:

- **_make(iterable) from collections.Point**
            Make a new Point object from a sequence or iterable

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(_cls, x: ForwardRef('int'), y: ForwardRef('int')) from namedtuple_Point.Point**
- **Create new instance of Point(x, y)**

        ----------------------------------------------------------------------
        Data descriptors defined here:

        x
            Alias for field number 0

        y
            Alias for field number 1

        ----------------------------------------------------------------------
        Data and other attributes defined here:

- **__annotations__ = {'x': ForwardRef('int'), 'y': ForwardRef('int')}**

- **__match_args__ = ('x', 'y')**

- **__orig_bases__ = (<function NamedTuple>,)**

        _field_defaults = {}

- **_fields = ('x', 'y')**

        ----------------------------------------------------------------------

### class Port(builtins.tuple)
- **Port(**
- **x: ForwardRef('int'),**
- **y: ForwardRef('int'),**
- **name: ForwardRef('str'),**
- **dim: ForwardRef('int'),**
- **type: ForwardRef('NodeType'),**
- **electrical: ForwardRef('Electrical'),**
- **signal: ForwardRef('Signal')**
        )

- **A named Port (input, output, or electrical connection) for a Component**

        Method resolution order:
            Port
            builtins.tuple
            builtins.object

        Methods defined here:

- **__getnewargs__(self) from collections.Port**
            Return self as a plain tuple.  Used by copy and pickle.

- **__replace__ = _replace(self, /, **kwds)**

- **__repr__(self) from collections.Port**
            Return a nicely formatted representation string

- **_asdict(self) from collections.Port**
            Return a new dict which maps field names to their values.

- **_replace(self, /, **kwds) from collections.Port**
            Return a new Port object replacing specified fields with new values

        ----------------------------------------------------------------------
        Class methods defined here:

- **_make(iterable) from collections.Port**
            Make a new Port object from a sequence or iterable

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(**
            _cls,
- **x: ForwardRef('int'),**
- **y: ForwardRef('int'),**
- **name: ForwardRef('str'),**
- **dim: ForwardRef('int'),**
- **type: ForwardRef('NodeType'),**
- **electrical: ForwardRef('Electrical'),**
- **signal: ForwardRef('Signal')**
        ) from namedtuple_Port.Port
- **Create new instance of Port(x, y, name, dim, type, electrical, signal)**

        ----------------------------------------------------------------------
        Readonly properties defined here:

        location
            Location of the Port.

            .. versionadded:: 3.0.2

        ----------------------------------------------------------------------
        Data descriptors defined here:

        x
            Alias for field number 0

        y
            Alias for field number 1

        name
            Alias for field number 2

        dim
            Alias for field number 3

        type
            Alias for field number 4

        electrical
            Alias for field number 5

        signal
            Alias for field number 6

        ----------------------------------------------------------------------
        Data and other attributes defined here:

- **__annotations__ = {'dim': ForwardRef('int'), 'electrical': ForwardRef(...**

- **__match_args__ = ('x', 'y', 'name', 'dim', 'type', 'electrical', 'sign...**

- **__orig_bases__ = (<function NamedTuple>,)**

        _field_defaults = {}

- **_fields = ('x', 'y', 'name', 'dim', 'type', 'electrical', 'signal')**

        ----------------------------------------------------------------------

### class ProjectType(enum.IntEnum)
- **ProjectType(*values)**

        Project Types

        Method resolution order:
            ProjectType
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        CASE = <ProjectType.CASE: 1>

        LIBRARY = <ProjectType.LIBRARY: 2>

        ----------------------------------------------------------------------

### class Rect(builtins.tuple)
- **Rect(**
- **left: ForwardRef('int'),**
- **top: ForwardRef('int'),**
- **right: ForwardRef('int'),**
- **bottom: ForwardRef('int')**
        )

        A class to represent rectangles on the canvas that supports mid-point
        calculation.

        Examples
        ---------
- **>>> rect = Rect(10, 10, 20, 20)**
            >>> rect
- **Rect(left=10, top=10, right=20, bottom=20)**
            >>> rect.mid
- **Point(x=15, y=15)**

        .. versionadded:: 2.9.6

        Method resolution order:
            Rect
            builtins.tuple
            builtins.object

        Methods defined here:

- **__getnewargs__(self) from collections.Rect**
            Return self as a plain tuple.  Used by copy and pickle.

- **__replace__ = _replace(self, /, **kwds)**

- **__repr__(self) from collections.Rect**
            Return a nicely formatted representation string

- **_asdict(self) from collections.Rect**
            Return a new dict which maps field names to their values.

- **_replace(self, /, **kwds) from collections.Rect**
            Return a new Rect object replacing specified fields with new values

        ----------------------------------------------------------------------
        Class methods defined here:

- **_make(iterable) from collections.Rect**
            Make a new Rect object from a sequence or iterable

- **from_mid(mid_point: 'Union[Tuple[int, int], Point]', w: 'int', h: 'int') -> 'Rect'** `@classmethod` -> `Rect`
                Initializes a rectangle given mid-point, width and height.
                For even ``w`` and/or ``h``, mid-point would not be exactly at the
                centre but closer to top left corner.

            Examples
            ---------
- **>>> mid = (10, 10)**
- **>>> Rect.from_mid(mid, 6,4)** `@classmethod` -> `Rect`
- **Rect(left=8, top=9, right=13, bottom=12)**

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(**
            _cls,
- **left: ForwardRef('int'),**
- **top: ForwardRef('int'),**
- **right: ForwardRef('int'),**
- **bottom: ForwardRef('int')**
        ) from namedtuple_Rect.Rect
- **Create new instance of Rect(left, top, right, bottom)**

        ----------------------------------------------------------------------
        Readonly properties defined here:

        height
            Height of the rectangle

        mid
            Returns the mid-point of rectangle. For even ``w`` and/or ``h``,
            mid-point would not be exactly at the centre but closer to top left corner.

        width
            Width of the rectangle

        ----------------------------------------------------------------------
        Data descriptors defined here:

        left
            Alias for field number 0

        top
            Alias for field number 1

        right
            Alias for field number 2

        bottom
            Alias for field number 3

        ----------------------------------------------------------------------
        Data and other attributes defined here:

- **__annotations__ = {'bottom': ForwardRef('int'), 'left': ForwardRef('in...**

- **__match_args__ = ('left', 'top', 'right', 'bottom')**

- **__orig_bases__ = (<function NamedTuple>,)**

        _field_defaults = {}

- **_fields = ('left', 'top', 'right', 'bottom')**

        ----------------------------------------------------------------------

### class Side(enum.IntEnum)
- **Side(*values)**

        Annotation Side

        Method resolution order:
            Side
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        AUTO = <Side.AUTO: 5>

        BOTTOM = <Side.BOTTOM: 4>

        LEFT = <Side.LEFT: 1>

        NONE = <Side.NONE: 0>

        RIGHT = <Side.RIGHT: 3>

        TOP = <Side.TOP: 2>

        ----------------------------------------------------------------------

### class Signal(enum.IntEnum)
- **Signal(*values)**

        Data Signal Types

        Method resolution order:
            Signal
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        COMPLEX = <Signal.COMPLEX: 4>

        ELECTRICAL = <Signal.ELECTRICAL: 0>

        INTEGER = <Signal.INTEGER: 2>

        LOGICAL = <Signal.LOGICAL: 1>

        REAL = <Signal.REAL: 3>

        UNKNOWN = <Signal.UNKNOWN: 15>

        ----------------------------------------------------------------------

### class Size(builtins.tuple)
- **Size(width: ForwardRef('int'), height: ForwardRef('int'))**

- **A class to represent rectangular size (width & height).**

        .. versionadded:: 3.0.11

        Method resolution order:
            Size
            builtins.tuple
            builtins.object

        Methods defined here:

- **__getnewargs__(self) from collections.Size**
            Return self as a plain tuple.  Used by copy and pickle.

- **__replace__ = _replace(self, /, **kwds)**

- **__repr__(self) from collections.Size**
            Return a nicely formatted representation string

- **_asdict(self) from collections.Size**
            Return a new dict which maps field names to their values.

- **_replace(self, /, **kwds) from collections.Size**
            Return a new Size object replacing specified fields with new values

        ----------------------------------------------------------------------
        Class methods defined here:

- **_make(iterable) from collections.Size**
            Make a new Size object from a sequence or iterable

        ----------------------------------------------------------------------
        Static methods defined here:

- **__new__(_cls, width: ForwardRef('int'), height: ForwardRef('int')) from namedtuple_Size.Size**
- **Create new instance of Size(width, height)**

        ----------------------------------------------------------------------
        Data descriptors defined here:

        width
            Alias for field number 0

        height
            Alias for field number 1

        ----------------------------------------------------------------------
        Data and other attributes defined here:

- **__annotations__ = {'height': ForwardRef('int'), 'width': ForwardRef('i...**

- **__match_args__ = ('width', 'height')**

- **__orig_bases__ = (<function NamedTuple>,)**

        _field_defaults = {}

- **_fields = ('width', 'height')**

        ----------------------------------------------------------------------

### class View(enum.IntEnum)
- **View(*values)**

        View Tabs

        Method resolution order:
            View
            enum.IntEnum
            builtins.int
            enum.ReprEnum
            enum.Enum
            builtins.object

        Methods defined here:

- **__format__(self, format_spec, /) from builtins.int**
            Convert to a string according to format_spec.

- **__new__(cls, value) from enum.Enum**
- **Create and return a new object.  See help(type) for accurate signature.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        DATA = <View.DATA: 3>

        FORTRAN = <View.FORTRAN: 2>

        GRAPHIC = <View.GRAPHIC: 4>

        PARAMETERS = <View.PARAMETERS: 5>

        SCHEMATIC = <View.SCHEMATIC: 1>

        SCRIPT = <View.SCRIPT: 6>

        ----------------------------------------------------------------------

## FUNCTIONS
    sqrt(x, /)
        Return the square root of x.

## DATA
    AnyPoint = typing.Union[mhi.pscad.types.Point, mhi.pscad.types.Port, t...
    BUILTIN_COMPONENTS = frozenset({'BookmarkCmp', 'Bus', 'Button', 'Cable...
    BUILTIN_COMPONENT_ALIAS = {'Bookmark': 'BookmarkCmp', 'StickyWire': 'W...
    Dict = typing.Dict
        A generic version of dict.

    ParameterRange = typing.Union[typing.Tuple, typing.Set, range, NoneTyp...
    Parameters = typing.Dict[str, typing.Any]
    Set = typing.Set
        A generic version of set.

    Tuple = typing.Tuple
        Deprecated alias to builtins.tuple.

        Tuple[X, Y] is the cross-product type of X and Y.

        Example: Tuple[T1, T2] is a tuple of two elements corresponding
        to type variables T1 and T2.  Tuple[int, float, str] is a tuple
        of an int, a float and a string.

        To specify a variable-length tuple of homogeneous type, use Tuple[T, ...].

    Union = typing.Union
        Union type; Union[X, Y] means either X or Y.

        On Python 3.10 and higher, the   operator
        can also be used to denote unions;
        X   Y means the same thing to the type checker as Union[X, Y].

        To define a union, use e.g. Union[int, str]. Details:
        - The arguments must be types and there must be at least one.
        - None as an argument is a special case and is replaced by
          type(None).
        - Unions of unions are flattened, e.g.::

            assert Union[Union[int, str], float] == Union[int, str, float]

        - Unions of a single argument vanish, e.g.::

            assert Union[int] == int  # The constructor actually returns int

        - Redundant arguments are skipped, e.g.::

            assert Union[int, str, int] == Union[int, str]

        - When comparing unions, the argument order is ignored, e.g.::

            assert Union[int, str] == Union[str, int]

        - You cannot subclass or instantiate a union.
        - You can use Optional[X] as a shorthand for Union[X, None].

## FILE
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/types.py
