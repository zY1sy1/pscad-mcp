# Module mhi.pscad.graphics

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/graphics.py*

Python Library Documentation: module mhi.pscad.graphics in mhi.pscad

## NAME
    mhi.pscad.graphics

## DESCRIPTION
    ===================
    Graphics Components
    ===================

    .. versionadded:: 2.2

## CLASSES
    enum.Enum(builtins.object)
        Gfx
    mhi.pscad.canvas.Canvas(mhi.pscad.remote.Remotable)
        GfxCanvas
    mhi.pscad.component.MovableMixin(builtins.object)
        GfxComponent(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin)
            GfxBase
                Arc
                Line
                Oval
                Rect(GfxBase, mhi.pscad.component.SizeableMixin)
                Shape
            Port
            Text
    mhi.pscad.component.ZComponent(mhi.pscad.remote.Remotable)
        GfxComponent(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin)
            GfxBase
                Arc
                Line
                Oval
                Rect(GfxBase, mhi.pscad.component.SizeableMixin)
                Shape
            Port
            Text

### class Arc(GfxBase)
- **Arc(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        The Graphic Canvas Arc Component

        .. versionadded:: 2.2

        Method resolution order:
            Arc
            GfxBase
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxBase:

- **vertices(self, *vertices)**
- **GfxBase.vertices([vertices])**

            Set or get the vertices of the a graphic element

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class Gfx(enum.Enum)
- **Gfx(*values)**

        Enumeration constants, representing various graphical shapes

        .. versionadded:: 2.2

        Method resolution order:
            Gfx
            enum.Enum
            builtins.object

        Data and other attributes defined here:

- **Arc = <Gfx.Arc: (3,)>**

- **ArrowDown = <Gfx.ArrowDown: (6, 11)>**

- **ArrowLeft = <Gfx.ArrowLeft: (6, 12)>**

- **ArrowRight = <Gfx.ArrowRight: (6, 10)>**

- **ArrowUp = <Gfx.ArrowUp: (6, 9)>**

- **Bezier = <Gfx.Bezier: (6, 0)>**

- **Constant = <Gfx.Constant: (6, 20)>**

- **Diamond = <Gfx.Diamond: (6, 4)>**

- **Heart = <Gfx.Heart: (6, 18)>**

- **Hexagon = <Gfx.Hexagon: (6, 8)>**

- **Lightning = <Gfx.Lightning: (6, 19)>**

- **Line = <Gfx.Line: (0,)>**

- **Node = <Gfx.Node: (5,)>**

- **Oval = <Gfx.Oval: (2,)>**

- **Parallelogram = <Gfx.Parallelogram: (6, 5)>**

- **Pentagon = <Gfx.Pentagon: (6, 7)>**

- **Rect = <Gfx.Rect: (1,)>**

- **RectRound = <Gfx.RectRound: (6, 1)>**

- **Shape = <Gfx.Shape: (6,)>**

- **SpeachOval = <Gfx.SpeachOval: (6, 17)>**

- **SpeachRect = <Gfx.SpeachRect: (6, 16)>**

- **Star4 = <Gfx.Star4: (6, 13)>**

- **Star5 = <Gfx.Star5: (6, 14)>**

- **Star6 = <Gfx.Star6: (6, 15)>**

- **Text = <Gfx.Text: (4,)>**

- **Trapezoid = <Gfx.Trapezoid: (6, 6)>**

- **TriangleIso = <Gfx.TriangleIso: (6, 3)>**

- **TriangleRight = <Gfx.TriangleRight: (6, 2)>**

        ----------------------------------------------------------------------

### class GfxBase(GfxComponent)
- **GfxBase(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Superclass for lines, rectangles, ellipses, arcs and other shapes.

        .. versionadded:: 2.2

        Method resolution order:
            GfxBase
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **vertices(self, *vertices)**
- **GfxBase.vertices([vertices])**

            Set or get the vertices of the a graphic element

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class GfxCanvas(mhi.pscad.canvas.Canvas)
- **GfxCanvas(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A graphics canvas is a surface where graphic components can be placed and
        arranged.

        The graphic canvas is accessed with
        :meth:`defn.graphics <.Definition.graphics>`.

        .. versionadded:: 2.2

        Method resolution order:
            GfxCanvas
            mhi.pscad.canvas.Canvas
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **add_electrical(**
            self,
            location: Tuple[int, int],
            name: str,
            dim: int = 1,
            electype: str = 'FIXED'
        )
            Add an electrical connection port to the component definition.

- **add_input(**
            self,
            location: Tuple[int, int],
            name: str,
            dim: int = 1,
            datatype: str = 'REAL'
        )
            Add a control signal input port to the component definition.

- **add_line(**
            self,
            p1: Tuple[int, int],
            p2: Tuple[int, int],
            *,
            color: str = 'black',
            dasharray: str = 'SOLID',
            thickness: str = '02_PT',
            port: str = '',
            cond: str = 'true',
            arrow_head: Optional[Tuple[int, int]] = None
        )
            Add a line to the component graphics.

- **add_output(**
            self,
            location: Tuple[int, int],
            name: str,
            dim: int = 1,
            datatype: str = 'REAL'
        )
            Add a control signal output port to the component definition.

- **add_port(**
            self,
            location: Tuple[int, int],
            name: str,
            mode: str,
            *,
            dim: int = 1,
            **kwargs
        )
            Add a port to the component definition.

- **add_rectangle(**
            self,
            p1: Tuple[int, int],
            p2: Tuple[int, int],
            *,
            color: str = 'black',
            dasharray: str = 'SOLID',
            thickness: str = '02_PT',
            port: str = '',
            fill_style: str = 'HOLLOW',
            fill_fg: str = 'black',
            fill_bg: str = 'black',
            cond: str = 'true'
        )
            Add a rectangle to the component graphics.

- **add_text(**
            self,
            location: Tuple[int, int],
            text: str,
            *,
            cond: str = 'true',
            color: str = 'black',
            anchor: str = 'LEFT',
            full_font: str = 'Tahoma, 10pt',
            angle: float = 0.0
        )
            Add a text label to the component graphics.

- **create_component(**
            self,
            shape: mhi.pscad.graphics.Gfx,
            extra: Union[mhi.pscad.graphics.Gfx, int, NoneType] = None
        )
            Create a new graphic object on a Graphics canvas.

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.canvas.Canvas:

- **__repr__(self)**
- **Return repr(self).**

- **add_component(**
            self,
            library: 'str',
            name: 'str',
            x: 'int' = 1,
            y: 'int' = 1,
            orient: 'int' = 0,
            **parameters
        ) -> 'Component'
            Create a new user component and add it to the canvas.

            Parameters:
- **library (str): Library the definition may be found in.**
- **name (str): Name of the component definition in the library.**
- **x (int): X location of the component (in grid units).**
- **y (int): Y location of the component (in grid units).**

            Returns:
                The created :class:`.Component`.

            .. versionchanged:: 2.0
                Added ``orient`` and ``**parameters``

- **bounds(self, components: 'Sequence[Component]') -> 'List[Rect]'**
            Return a list of the bounds of the given components.

            Equivalent to ``[cmp.bounds for cmp in components]`` but without
            the round trip to the server for each component.

            .. versionadded:: 2.9.6

- **clear_selection(self)**
            Reset the selection so that no components are selected.

- **closest_empty_rect(**
            self,
            w: 'int',
            h: 'int',
            point: 'Union[Tuple[int, int], Point]'
        ) -> 'Rect'
            Returns an empty rectangle with the size provided, closest to
            the given point.

            Parameters
            ----------
            w: int
                Width of the empty rectangle.
            h: int
                Height of the empty rectangle.
            point: Union[Tuple[int, int], Point]
                The point to which the nearest empty rectangle is found.

            Returns
            ----------
            Rect
                Closest empty rectangle to the given point.


            .. versionadded:: 2.9.6

- **component(self, iid: 'int') -> 'Component'**
            Retrieve a component by ID.

            Parameters:
- **iid (int): The ID attribute of the component.**

            .. versionadded:: 2.0
                This command replaces all of the type specific versions.

- **components(self) -> 'List[Component]'**
            Get a list of all components on the canvas.

- **This is equivalent to calling ``Project.find_all()``,**
            where no filter criteria is used to select a subset of components.

            Returns:
                List[Component]: The list of components

            .. versionadded:: 2.0

- **copy(self, *components: 'Component') -> 'bool'**
            Copy the given list of components, or currently selected components
            if no components are given, to the clipboard.

            Parameters:
- ***components (List[Component]): Components to be copied (optional)**

            .. versionchanged:: 2.1
                Added optional list of ``components``

- **cut(self, *components: 'Component') -> 'bool'**
            Cut the given list of components, or currently selected components
            if no components are given, to the clipboard.

            Parameters:
- ***components (List[Component]): Components to be cut (optional)**

            .. versionchanged:: 2.1
                Added optional list of ``components``

- **delete(self, *components: 'Component') -> 'bool'**
            Delete the given list of components, or currently selected components
            if no components are given.

            Parameters:
- ***components (List[Component]): Components to be deleted (optional)**

            .. versionchanged:: 2.1
                Added optional list of ``components``

- **find(self, *names: 'str', layer: 'Optional[str]' = None, **params) -> 'Optional[Component]'**
- **find( [[definition,] name,] [layer=name,] [key=value, ...])**

- **Find the (singular) component that matches the given criteria,**
            or ``None`` if no matching component can be found.
            Raises an exception if more than one component matches
            the given criteria.

- **find_all(self, *name: 'str', layer: 'Optional[str]' = None, **params) -> 'List[Component]'**
- **find_all( [[definition,] name,] [layer=name,] [key=value, ...])**

            Find all components that match the given criteria.
            If no criteria is given, all components on the canvas are returned.

            Parameters:
- **definition (str): One of "Bus", "TLine", "Cable", "GraphFrame",**
                    "Sticky", or a colon-seperated definition name, such as
- **"master:source3" (optional)**
- **name (str): the component's name, as given by a parameter**
                    called "name", "Name", or "NAME".
                    If no definition was given, and if the provided name is
                    "Bus", "TLine", "Cable", "GraphFrame", "Sticky", or
                    contains a colon, it is treated as the definition name.
- **(optional)**
- **layer (str): only return components on the given layer (optional)**
                key=value: A keyword list specifying additional parameters
                   which must be matched.  Parameter names and values must match
                   exactly. For example, Voltage="230 [kV]" will not match
                   components with a Voltage parameter value of "230.0 [kV]".
- **(optional)**

            Returns:
                List[Component]: The list of matching components,
                or an empty list if no matching components are found.

            Examples::

- **c = find_all('Bus')               # all Bus components**
- **c = find_all('Bus10')             # all components named "Bus10"**
- **c = find_all('Bus', 'Bus10')      # all Bus component named "Bus10"**
- **c = find_all('Bus', BaseKV='138') # all Buses with BaseKV="138"**
- **c = find_all(BaseKV='138')        # all components with BaseKV="138"**

- **find_first(self, *names: 'str', layer: 'Optional[str]' = None, **params) -> 'Optional[Component]'**
- **find_first( [[definition,] name,] [layer=name,] [key=value, ...])**

            Find the first component that matches the given criteria,
            or ``None`` if no matching component can be found.

- **flip(self, *components: 'Component') -> 'bool'**
            Flip the given list of components, or the currently selected
            components if no components are given, along the vertical axis.

            Parameters:
- ***components (List[Component]): Components to be flipped (optional)**

- **get_empty_rects(self, w: 'int', h: 'int') -> 'List[Rect]'**
            Returns empty rectangle spaces on the canvas.

            Parameters
            ----------
            w: int
                Width of the empty rectangles.
            h: int
                Height of the empty rectangles.

            Returns
            ----------
            List[Rect]
                List of empty rectangles.


            .. versionadded:: 2.9.6

- **list_components(self)**

- **mirror(self, *components: 'Component') -> 'bool'**
            Mirror the given list of components, or the currently selected
            components if no components are given, along the horizontal axis.

            Parameters:
- ***components (List[Component]): Components to be mirrored (optional)**

- **names_in_use(self, defn: 'Optional[str]' = None, **params) -> 'Set[str]'**
            Return the set of "Name" parameter values, for all components on the
            canvas that have a "Name" parameter.

            .. versionadded:: 3.0.0

- **navigate_up(self) -> 'None'**
            Navigate to parent page

- **parameter_range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a setting

            .. versionadded:: 2.1

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Get or set canvas parameters

            .. table:: Canvas Parameters

                =================== ===== ==========================================
                Param Name          Type  Description
                =================== ===== ==========================================
                auto_sequence       str   'MANUAL', 'AUTOMATIC'
                show_border         bool  Display re-sizing border
                monitor_bus_voltage bool  Display dynamic voltage levels on buses
                show_grid           bool  Show connection grid
                show_signal         bool  Show all locations tracked in signal table
                show_terminals      bool  Show where equipment ports are terminated
                show_sequence       bool  Display sequence order numbers
                show_virtual        bool  Show virtual wired signal relations
                virtual_filter      str   Comma separated signal names to show
- **animation_freq      int   How often components are redrawn (msec)**
                orient              str   'LANDSCAPE', 'PORTRAIT'
                size                str   '85X11', '11X17', '17X22', '22X34',
                                          '34X44', '100X100'
                =================== ===== ==========================================

            .. versionadded:: 2.1

- **paste(self, mouse_x: 'int', mouse_y: 'int') -> 'bool'**
            Paste the contents of the clipboard into this canvas at the
            indicated mouse location.

            .. versionchanged:: 2.1
                Added ``mouse_x`` and ``mouse_y``

- **rotate_180(self, *components: 'Component') -> 'bool'**
            Rotate the given list of components, or the currently selected
            components if no components are given, 180 degrees.

            Parameters:
- ***components (List[Component]): Components to be rotated (optional)**

- **rotate_left(self, *components: 'Component') -> 'bool'**
            Rotate the given list of components, or the currently selected
            components if no components are given, 90 degrees counter-clockwise.

            Parameters:
- ***components (List[Component]): Components to be rotated (optional)**

- **rotate_right(self, *components: 'Component') -> 'bool'**
            Rotate the given list of components, or the currently selected
            components if no components are given, 90 degrees clockwise.

            Parameters:
- ***components (List[Component]): Components to be rotated (optional)**

- **select(self, *components: 'Component')**
            Place specific components in the current selection.

            Parameters:
- **components (list): the components to be selected.**

            .. versionadded:: 2.0

- **select_components(**
            self,
            x1: 'int',
            y1: 'int',
            x2: 'Optional[int]' = None,
            y2: 'Optional[int]' = None,
            width: 'Optional[int]' = None,
            height: 'Optional[int]' = None
        )
            Select components in a rectangular area.

            If width and height are used, the x1,y1 values are interpreted as the
            lower-left corner of the region.  If both x1,y1 and x2,y2 are given,
            any opposite corners may be used and the rectangle will be normalized
            for the user automatically.

            All values are in grid coordinates.

            Parameters:
- **x1 (int): lower left corner of the selection region**
- **y1 (int): lower left corner of the selection region**
- **x2 (int): upper right corner of the selection region (optional)**
- **y2 (int): upper right corner of the selection region (optional)**
- **width (int): width of the selection region (optional)**
- **height (int): height of the selection region (optional)**

- **selection(self) -> 'List[Component]'**
            Retrieve the components which are selected on the canvas.

            .. versionadded:: 2.3.2

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.canvas.Canvas:

        name
- **The name of the definition (read-only)**

            .. versionadded:: 2.0

        scope
- **The name of the project (read-only)**

            .. versionadded:: 2.0

        size
            Canvas size, in grid units

            .. versionadded:: 2.9.6

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

### class GfxComponent(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin)
- **GfxComponent(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A component which can exist on a User Component's Definition's GfxCanvas.

- **Includes visible components (lines, text, curves, ...) and invisible**
- **components (ports).**

        .. versionadded:: 2.2

        Method resolution order:
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class Line(GfxBase)
- **Line(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        The Graphic Canvas Line Component

        .. versionadded:: 2.2

        Method resolution order:
            Line
            GfxBase
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxBase:

- **vertices(self, *vertices)**
- **GfxBase.vertices([vertices])**

            Set or get the vertices of the a graphic element

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class Oval(GfxBase)
- **Oval(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        The Graphic Canvas Oval Component

        .. versionadded:: 2.2

        Method resolution order:
            Oval
            GfxBase
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxBase:

- **vertices(self, *vertices)**
- **GfxBase.vertices([vertices])**

            Set or get the vertices of the a graphic element

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class Port(GfxComponent)
- **Port(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        An Input, Output or Electrical connection to the component.

        .. versionadded:: 2.2

        Method resolution order:
            Port
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class Rect(GfxBase, mhi.pscad.component.SizeableMixin)
- **Rect(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        The Graphic Canvas Rectangle Component

        .. versionadded:: 2.2

        Method resolution order:
            Rect
            GfxBase
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxBase:

- **vertices(self, *vertices)**
- **GfxBase.vertices([vertices])**

            Set or get the vertices of the a graphic element

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.SizeableMixin:

- **get_size(self) -> 'Tuple[int, int]'**

- **set_size(self, width: 'int', height: 'int') -> 'None'**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.SizeableMixin:

        size
            Set/get width & height of a sizeable component

### class Shape(GfxBase)
- **Shape(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        The Graphic Canvas General Shape Component

        May represent a Bezier, RectRound, TriangleRight, TriangleIso, Diamond,
        Parallelogram, Trapezoid, Pentagon, Hexagon, ArrowUp, ArrowRight,
        ArrowDown, ArrowLeft, Star4, Star5, Star6, SpeachRect, SpeachOval,
        Heart, Lightning, or Constant.

        .. versionadded:: 2.2

        Method resolution order:
            Shape
            GfxBase
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxBase:

- **vertices(self, *vertices)**
- **GfxBase.vertices([vertices])**

            Set or get the vertices of the a graphic element

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

### class Text(GfxComponent)
- **Text(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        The Graphic Canvas Text Component

        .. versionadded:: 2.2

        Method resolution order:
            Text
            GfxComponent
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from GfxComponent:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'**

- **add_to_layer(self, name: 'str') -> 'None'**
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'**
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'**
            Set a custom layer state for this component.

            The component must already be part of a layer, and that layer must
            already have the named custom state :meth:`added <.Layer.add_state>`
            to it.  This component will be set to the given state when the
            component's layer is set to the given custom state name.

            Parameters:
- **state_name (str): The component's layer's custom state name**
- **state (str): One of 'Enabled', 'Disabled' or 'Invisible'**

        defn_name = <functools.cached_property object>
- **The name of the definition (read-only)**

            .. versionchanged:: 3.0.2
                Return type changed from ``Union[str, Tuple[str, str]]`` to ``str``.
                For a three-phased voltage source for instance, the return value
                changed from ``'master', 'source3'`` to ``'master:source3'``

- **disable(self) -> 'None'**
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'**
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)**

- **export_parameters(self, csvfile: 'str') -> 'None'**
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)**

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'**
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)**

- **to_back(self) -> 'bool'**
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'**
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'**
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'**
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'**
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.ZComponent:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.remote.Remotable:

        main
            A reference to the :class:`.Application` object that returned this
            ``Remotable`` object.

        ----------------------------------------------------------------------
        Methods inherited from mhi.common.remote.Remotable:

- **__eq__(self, other)**
            Return self==value.

- **__hash__(self)**
- **Return hash(self).**

- **__init__(**
            self,
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__ne__(self, other)**
            Return self!=value.

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.MovableMixin:

- **copy(self) -> 'bool'**
            Copy this component to the clipboard.

- **cut(self) -> 'bool'**
            Cut this component to the clipboard

- **delete(self) -> 'bool'**
            Delete this component.

- **get_location(self)**
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)**
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties inherited from mhi.pscad.component.MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.MovableMixin:

        bounds
            The left, top, right and bottom bounds of the component, in grid units
- **(read only)**

            :type: Rect


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

        location
- **Component (X, Y) location, in grid units**


            When this property is retrieved, it will be cached for
            5.0 seconds, and if retrieved again within that time the
            cached value will be returned.

## DATA
    LOG = <Logger mhi.pscad.graphics (INFO)>
    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

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
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/graphics.py
