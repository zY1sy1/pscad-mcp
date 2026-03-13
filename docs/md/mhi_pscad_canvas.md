# Module mhi.pscad.canvas

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/canvas.py*

Python Library Documentation: module mhi.pscad.canvas in mhi.pscad

## NAME
    mhi.pscad.canvas

## DESCRIPTION
    ======
    Canvas
    ======

## CLASSES
    mhi.pscad.remote.Remotable(mhi.common.remote.Remotable)
        Canvas
            UserCanvas

### class Canvas(mhi.pscad.remote.Remotable)
- **Canvas(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A canvas is a surface where components can be placed and arranged.
        A "user canvas" is the most general version of a canvas.
- **(T-Line and Cable canvases are more restrictive, permitting only certain**
        types of components.)

        The main page of a project is typically retrieved with::

- **main = project.canvas('Main')**

        Method resolution order:
            Canvas
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **add_component(** -> `Component`
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
- **name (str): Name of the component definition in the library.** `@property` -> `str`
- **x (int): X location of the component (in grid units).**
- **y (int): Y location of the component (in grid units).**

            Returns:
                The created :class:`.Component`.

            .. versionchanged:: 2.0
                Added ``orient`` and ``**parameters``

- **bounds(self, components: 'Sequence[Component]') -> 'List[Rect]'** `@requires` -> `List[Rect]`
            Return a list of the bounds of the given components.

            Equivalent to ``[cmp.bounds for cmp in components]`` but without
            the round trip to the server for each component.

            .. versionadded:: 2.9.6

- **clear_selection(self)**
            Reset the selection so that no components are selected.

- **closest_empty_rect(** `@requires` -> `Rect`
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

- **component(self, iid: 'int') -> 'Component'** `@rmi` -> `Component`
            Retrieve a component by ID.

            Parameters:
- **iid (int): The ID attribute of the component.**

            .. versionadded:: 2.0
                This command replaces all of the type specific versions.

- **components(self) -> 'List[Component]'** -> `List[Component]`
            Get a list of all components on the canvas.

- **This is equivalent to calling ``Project.find_all()``,** -> `List[Component]`
            where no filter criteria is used to select a subset of components.

            Returns:
                List[Component]: The list of components

            .. versionadded:: 2.0

- **copy(self, *components: 'Component') -> 'bool'** -> `bool`
            Copy the given list of components, or currently selected components
            if no components are given, to the clipboard.

            Parameters:
- ***components (List[Component]): Components to be copied (optional)** -> `List[Component]`

            .. versionchanged:: 2.1
                Added optional list of ``components``

- **create_component(** -> `Component`
            self,
            defn: 'Union[str, Definition]',
            x: 'int' = 1,
            y: 'int' = 1,
            orient: 'int' = 0,
            **parameters
        ) -> 'Component'
            Create a new component and add it to the canvas.

            Parameters:
- **defn (Union[str, Definition]): Type of component to create**
- **x (int): X location of the component (in grid units).**
- **y (int): Y location of the component (in grid units).**
- **orient (int): Rotation/mirroring of the component**
                parameters: key=value pairs

            Returns:
                The created :class:`.Component`.

            .. versionadded:: 2.0

            .. versionchanged:: 2.2
                ``defn`` accepts a :class:`.Definition` or a string.

- **cut(self, *components: 'Component') -> 'bool'** -> `bool`
            Cut the given list of components, or currently selected components
            if no components are given, to the clipboard.

            Parameters:
- ***components (List[Component]): Components to be cut (optional)** -> `List[Component]`

            .. versionchanged:: 2.1
                Added optional list of ``components``

- **delete(self, *components: 'Component') -> 'bool'** -> `bool`
            Delete the given list of components, or currently selected components
            if no components are given.

            Parameters:
- ***components (List[Component]): Components to be deleted (optional)** -> `List[Component]`

            .. versionchanged:: 2.1
                Added optional list of ``components``

- **find(self, *names: 'str', layer: 'Optional[str]' = None, **params) -> 'Optional[Component]'** -> `Optional[Component]`
- **find( [[definition,] name,] [layer=name,] [key=value, ...])** -> `Optional[Component]`

- **Find the (singular) component that matches the given criteria,**
            or ``None`` if no matching component can be found.
            Raises an exception if more than one component matches
            the given criteria.

- **find_all(self, *name: 'str', layer: 'Optional[str]' = None, **params) -> 'List[Component]'** -> `List[Component]`
- **find_all( [[definition,] name,] [layer=name,] [key=value, ...])** -> `List[Component]`

            Find all components that match the given criteria.
            If no criteria is given, all components on the canvas are returned.

            Parameters:
- **definition (str): One of "Bus", "TLine", "Cable", "GraphFrame",**
                    "Sticky", or a colon-seperated definition name, such as
- **"master:source3" (optional)**
- **name (str): the component's name, as given by a parameter** `@property` -> `str`
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

- **c = find_all('Bus')               # all Bus components** -> `List[Component]`
- **c = find_all('Bus10')             # all components named "Bus10"** -> `List[Component]`
- **c = find_all('Bus', 'Bus10')      # all Bus component named "Bus10"** -> `List[Component]`
- **c = find_all('Bus', BaseKV='138') # all Buses with BaseKV="138"** -> `List[Component]`
- **c = find_all(BaseKV='138')        # all components with BaseKV="138"** -> `List[Component]`

- **find_first(self, *names: 'str', layer: 'Optional[str]' = None, **params) -> 'Optional[Component]'** -> `Optional[Component]`
- **find_first( [[definition,] name,] [layer=name,] [key=value, ...])** -> `Optional[Component]`

            Find the first component that matches the given criteria,
            or ``None`` if no matching component can be found.

- **flip(self, *components: 'Component') -> 'bool'** -> `bool`
            Flip the given list of components, or the currently selected
            components if no components are given, along the vertical axis.

            Parameters:
- ***components (List[Component]): Components to be flipped (optional)** -> `List[Component]`

- **get_empty_rects(self, w: 'int', h: 'int') -> 'List[Rect]'** `@requires` -> `List[Rect]`
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

- **list_components(self)** `@deprecated`

- **mirror(self, *components: 'Component') -> 'bool'** -> `bool`
            Mirror the given list of components, or the currently selected
            components if no components are given, along the horizontal axis.

            Parameters:
- ***components (List[Component]): Components to be mirrored (optional)** -> `List[Component]`

- **names_in_use(self, defn: 'Optional[str]' = None, **params) -> 'Set[str]'** -> `Set[str]`
            Return the set of "Name" parameter values, for all components on the
            canvas that have a "Name" parameter.

            .. versionadded:: 3.0.0

- **navigate_up(self) -> 'None'** -> `None`
            Navigate to parent page

- **parameter_range(self, parameter: 'str') -> 'ParameterRange'** -> `ParameterRange`
            Get legal values for a setting

            .. versionadded:: 2.1

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
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

- **paste(self, mouse_x: 'int', mouse_y: 'int') -> 'bool'** -> `bool`
            Paste the contents of the clipboard into this canvas at the
            indicated mouse location.

            .. versionchanged:: 2.1
                Added ``mouse_x`` and ``mouse_y``

- **rotate_180(self, *components: 'Component') -> 'bool'** -> `bool`
            Rotate the given list of components, or the currently selected
            components if no components are given, 180 degrees.

            Parameters:
- ***components (List[Component]): Components to be rotated (optional)** -> `List[Component]`

- **rotate_left(self, *components: 'Component') -> 'bool'** -> `bool`
            Rotate the given list of components, or the currently selected
            components if no components are given, 90 degrees counter-clockwise.

            Parameters:
- ***components (List[Component]): Components to be rotated (optional)** -> `List[Component]`

- **rotate_right(self, *components: 'Component') -> 'bool'** -> `bool`
            Rotate the given list of components, or the currently selected
            components if no components are given, 90 degrees clockwise.

            Parameters:
- ***components (List[Component]): Components to be rotated (optional)** -> `List[Component]`

- **select(self, *components: 'Component')**
            Place specific components in the current selection.

            Parameters:
- **components (list): the components to be selected.** -> `List[Component]`

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

- **selection(self) -> 'List[Component]'** `@requires` -> `List[Component]`
            Retrieve the components which are selected on the canvas.

            .. versionadded:: 2.3.2

        ----------------------------------------------------------------------
        Readonly properties defined here:

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
        Data and other attributes defined here:

        __annotations__ = {}

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

### class UserCanvas(Canvas)
- **UserCanvas(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A user canvas is a surface where components can be placed and arranged.

        The main page of a project is typically retrieved with::

- **main = project.canvas('Main')**

        Method resolution order:
            UserCanvas
            Canvas
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **add_wire(self, *vertices)** `@deprecated`

- **bus = user_cmp(self, iid)** `@deprecated`

- **button = _get_by_last_id(self, *iid)** `@deprecated`

- **cable = user_cmp(self, iid)** `@deprecated`

- **compose_wires(self, *wires: 'Wire') -> 'bool'** -> `bool`
            Join connected wire segments into multisegment wires

- **copy_as_bitmap(self)** `@deprecated`

- **copy_as_metafile(self)** `@deprecated`

- **copy_controls(self, *controls)**

- **create_annotation(** -> `Component`
            self,
            x: 'int' = 1,
            y: 'int' = 1,
            line1: 'Optional[str]' = None,
            line2: 'Optional[str]' = None
        ) -> 'Component'
            Create a two-line annotation component.

            Parameters:
- **x (int): x-coordinate of the annotation (in grid units)**
- **y (int): y-coordinate of the annotation (in grid units)**
- **line1 (str): first line of text**
- **line2 (str): second line of text**

            Returns:
                Component: the created annotation

            .. versionchanged:: 2.1
                Added ``line1`` and ``line2`` parameters

- **create_bookmark_link(self, bookmark: 'int', x: 'int' = 1, y: 'int' = 1) -> 'Component'** -> `Component`
            Create a bookmark link, which can be used to navigate to a bookmarked
            location.

            Parameters:
                bookmark: value returned from :meth:`.Project.bookmark`
- **x (int): x-coordinate of the bookmark link (in grid units).**
- **y (int): y-coordinate of the bookmark link (in grid units).**

            Returns:
                Component: the bookmark link component

- **create_bus(self, *vertices: 'Tuple[int, int]') -> 'Bus'** -> `Bus`
- **create_bus( (x1,y1), (x2,y2), [... (xn,yn) ...])** -> `Bus`
            Create a new bus and add it to the canvas.

            If more than two vertices are given, a multi-vertex bus will be
            created.
            If any segment is neither horizontal or vertical, additional vertices
            will be inserted.

            Parameters:
- ***vertices: A series of (X, Y) pairs, in grid units**

            Returns:
                Bus: The created bus.

            Note:
- **Use :meth:`.UserCmp.port()` to determine the locations to connect**
                the wires to.

- **create_case_link(self, x=1, y=1, name=None, hyperlink=None)** `@deprecated`

- **create_connection(** -> `Optional[str]`
            self,
            p1: 'AnyPoint',
            p2: 'AnyPoint',
            *,
            label: 'Optional[str]' = None,
            electrical: 'Optional[bool]' = None
        ) -> 'Optional[str]'
            Creates a connection between two points. If ``label`` is not
- **provided (default), the connection is made using wires; otherwise,**
            ``electrical`` must be set to True/False to create electrical/data
            labels to connect points.

            Parameters
            ----------
            p1 : AnyPoint
                One of the two ends of connection
            p2 : AnyPoint
                The other end of connection
            label: str, optional
                Specifies the node label. A suffix, starting from "_2" is added to
                ``label`` until it is unique on canvas. Defaults to ``None``.
            electrical: bool, optional
                Set ``True``, for electrical and ``False`` for data node labels.
                Must be provided if ``label`` is specified. Defaults to ``None``.

            Returns
            -------
            Optional[str]
                Name of the node labels created if ``label`` is provided;
                otherwise, ``None``.


            .. versionadded:: 2.9.6

            .. versionchanged:: 3.0.2
                PSCAD 5.1 requirement is removed.

- **create_control_frame(** -> `Tuple[ControlFrame, List[Control]]`
            self,
            x: 'int' = 1,
            y: 'int' = 1,
            *control_components: 'Component'
        ) -> 'Tuple[ControlFrame, List[Control]]'
            Create a control frame

            Parameters:
- **x (int): X location of the control frame (in grid units).**
- **y (int): Y location of the control frame (in grid units).**

            Returns:
                Tuple[ControlFrame,List[Controls]]: the control frame & any controls

- **create_divider(** -> `Divider`
            self,
            x: 'int' = 1,
            y: 'int' = 1,
            *,
            width: 'Optional[int]' = None,
            height: 'Optional[int]' = None
        ) -> 'Divider'
            Create a divider component.

            Parameters:
- **x (int): x-coordinate of the divider (in grid units).**
- **y (int): y-coordinate of the divider (in grid units).**
- **width (int): horizontal length of the divider, or**
- **height (int): vertical height of the divider**

            Returns:
                Divider: the divider component

            .. versionchanged:: 2.1
                Added ``line1`` and ``line2`` parameters

- **create_divider_box(self, x: 'int', y: 'int', width: 'int', height: 'int') -> 'Tuple[Divider, Divider, Divider, Divider]'** -> `Tuple[Divider, Divider, Divider, Divider]`
            Create a rectangular box using a divider for each side

            Parameters:
- **x (int): left coordinate of the divider box (in grid units).**
- **y (int): top coordinate of the divider box (in grid units).**
- **width (int): horizontal length of the divider box.**
- **height (int): vertical height of the divider box.**

            Returns:
                Tuple[Divider, ...]: the top, left, bottom and right dividers

            .. versionadded:: 2.1

- **create_file(** -> `Component`
            self,
            x: 'int' = 1,
            y: 'int' = 1,
            name: 'Optional[str]' = None,
            path: 'Optional[str]' = None
        ) -> 'Component'
            Create a file link component

            Parameters:
- **x (int): x-coordinate of the file link (in grid units).**
- **y (int): y-coordinate of the file link (in grid units).**
- **name (str): name to display on the file link**
- **path (str): path to the linked file**

            Returns:
                Component: the file link component

            .. seealso:: :py:meth:`.Project.create_resource`

- **create_graph(self, pgb: 'Optional[PGB]' = None, x: 'int' = 1, y: 'int' = 1) -> 'Tuple[GraphFrame, OverlayGraph, Optional[Curve]]'** -> `Tuple[GraphFrame, OverlayGraph, Optional[Curve]]`
            Create an Graph Frame containing an Overlay Graph with a Signal

            Parameters:
- **pgb (Component): the PGB for the signal to add to the graph.**
- **x (int): X location of the graph frame (in grid units).**
- **y (int): Y location of the graph frame (in grid units).**

            Returns:
                Tuple[GraphFrame,OverlayGraph,Curve]: The new graph frame,             Overlay Graph, and Curve.

- **create_graph_frame(self, x: 'int' = 1, y: 'int' = 1) -> 'GraphFrame'** -> `GraphFrame`
            Create an empty Graph Frame

            Parameters:
- **x (int): X location of the graph frame (in grid units).**
- **y (int): Y location of the graph frame (in grid units).**

            Returns:
                GraphFrame: The graph frame

- **create_group_box(self, x: 'int' = 1, y: 'int' = 1, name: 'Optional[str]' = None) -> 'GroupBox'** `@requires` -> `GroupBox`
            Create a group box.

            Parameters:
- **x (int): x-coordinate of the group box (in grid units).**
- **y (int): y-coordinate of the group box (in grid units).**
- **name (str): Name (or caption) of group box.**

            Returns:
                GroupBox: The created group box.

            .. versionadded:: 2.9

- **create_hyper_link(** -> `Component`
            self,
            x: 'int' = 1,
            y: 'int' = 1,
            name: 'Optional[str]' = None,
            hyperlink: 'Optional[str]' = None
        ) -> 'Component'
            Create a hyper-link component

            Parameters:
- **x (int): x-coordinate of the hyper-link (in grid units).**
- **y (int): y-coordinate of the hyper-link (in grid units).**
- **name (str): name to display on the hyper-link**
- **hyperlink (str): URL to the linked resource**

            Returns:
                Component: the hyper-link component

- **create_oscilloscope(self, pgb: 'PGB', x: 'int' = 1, y: 'int' = 1) -> 'Oscilloscope'** -> `Oscilloscope`
            Create an oscilloscope from a PGB component

            Parameters:
- **pgb (Component): a PGB component.**
- **x (int): X location of the oscilloscope (in grid units).**
- **y (int): Y location of the oscilloscope (in grid units).**

            Returns:
                Oscilloscope: the oscilloscope component.

- **create_phasor_meter(** -> `PhasorMeter`
            self,
            pgb: 'PGB',
            x: 'int' = 1,
            y: 'int' = 1,
            angle: 'Optional[str]' = None
        ) -> 'PhasorMeter'
            Create a phasor meter from a PGB component

            Parameters:
- **pgb (Component): a PGB component.**
- **x (int): X location of the phasor meter (in grid units).**
- **y (int): Y location of the phasor meter (in grid units).**
- **angle (str): The input angle format ``"degrees"`` or ``"radians"``**

            Returns:
                PhasorMeter: the phasor meter component.

- **create_poly_meter(self, pgb: 'Optional[PGB]' = None, x: 'int' = 1, y: 'int' = 1) -> 'PolyMeter'** -> `PolyMeter`
            Create a polymeter from a PGB component

            Parameters:
- **pgb (Component): a PGB component.**
- **x (int): X location of the polymeter (in grid units).**
- **y (int): Y location of the polymeter (in grid units).**

            Returns:
                PolyMeter: the polymeter component.

- **create_polygraph(** -> `Tuple[GraphFrame, PolyGraph, Optional[Curve]]`
            self,
            pgb: 'Optional[PGB]' = None,
            x: 'int' = 1,
            y: 'int' = 1,
            digital: 'bool' = False
        ) -> 'Tuple[GraphFrame, PolyGraph, Optional[Curve]]'
            Create an Stacked PolyGraph with a Signal

            Parameters:
- **pgb (Component): the PGB for the signal to add to the graph.**
- **x (int): X location of the graph frame (in grid units).**
- **y (int): Y location of the graph frame (in grid units).**
- **digital (bool): Set to ``True`` to create a digital polygraph**

            Returns:
                Tuple[GraphFrame,PolyGraph,Curve]: The new graph frame,             PolyGraph, and Curve.

- **create_sticky_note(** -> `Sticky`
            self,
            x: 'int' = 1,
            y: 'int' = 1,
            text: 'Optional[str]' = None
        ) -> 'Sticky'
            Create a sticky note.

            Parameters:
- **x (int): x-coordinate of the sticky note (in grid units).**
- **y (int): y-coordinate of the sticky note (in grid units).**
- **text (str): Content of sticky note.**

            Returns:
                Sticky: The created sticky note.

- **create_sticky_wire(self, *vertices: 'Tuple[int, int]') -> 'StickyWire'** -> `StickyWire`
- **create_sticky_wire( (x1,y1), (x2,y2), [... (xn,yn) ...])** -> `StickyWire`
            Create a sticky wire between two or more vertices.

            All vertices will be connected to a central point via a short
            one grid unit horizontal or vertical segment, followed by a
            diagonal segment.

            Parameters:
- ***vertices: A series of (X, Y) pairs, in grid units**

            Returns:
                StickyWire: The created sticky wire.

- **create_wire(self, *vertices: 'Tuple[int, int]') -> 'Wire'** -> `Wire`
- **create_wire( (x1,y1), (x2,y2), [... (xn,yn) ...])** -> `Wire`
            Create a new wire and add it to the canvas.

            If more than two vertices are given, a multi-vertex wire will be
            created.
            If any segment is neither horizontal or vertical, additional vertices
            will be inserted.

            Parameters:
- ***vertices: A series of (X, Y) pairs, in grid units**

            Returns:
                Wire: The created wire.

            Note:
- **Use :meth:`.UserCmp.port()` to determine the locations to connect**
                the wires to.

            .. versionchanged:: 2.0
- **Replaces ``UserCanvas.add_wire(...)``** `@deprecated`

- **create_xy_plot(self, x: 'int' = 1, y: 'int' = 1, polar: 'bool' = False) -> 'PlotFrame'** -> `PlotFrame`
            Create an XY PlotFrame

            Parameters:
- **x (int): X location of the plot frame (in grid units).**
- **y (int): Y location of the plot frame (in grid units).**
- **polar (bool): Set to ``True`` to for the polar variant.**

            Returns:
                PlotFrame: The plot frame

- **cut_controls(self, *controls)**

- **decompose_wires(self, *wires: 'Wire') -> 'bool'** -> `bool`
            Split all of the segments of the wires into multiple simple wires

- **graph_frame = user_cmp(self, iid)** `@deprecated`

- **group(self, *components: 'Component') -> 'Component'** `@rmi` -> `Component`
            Group the given list of components into one group component.

            Parameters:
- ***components (List[Component]): Components to be grouped**

            Returns:
                Component: the Aggregate component

- **overlay_graph = _get_by_last_id(self, *iid)** `@deprecated`

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Get or set User Canvas parameters

            .. table:: User Canvas Settings

               =================== ======= ================================================
               Param Name          Type    Description
               =================== ======= ================================================
               auto_sequence       Choice  Sequence Ordering: MANUAL, AUTOMATIC
               show_border         Boolean Bounds
               monitor_bus_voltage Boolean Bus Monitoring
               show_grid           Boolean Grids
               show_signal         Boolean Signals
               show_terminals      Boolean Terminals
               show_sequence       Boolean Sequence Order Numbers
               show_virtual        Boolean Virtual Wires
               size                Choice  Size: 85X11, 11X17, 17X22, 22X34, 34X44, 100X100
               orient              Choice  Orientation: PORTRAIT, LANDSCAPE
               virtual_filter      Text    Virtual Wires Filter
               animation_freq      Integer Animation Update Frequency
               =================== ======= ================================================

            .. versionadded:: 2.1

- **paste_rename(self, mouse_x: 'int', mouse_y: 'int') -> 'bool'** -> `bool`
            Paste the contents of the clipboard and rename all the components
            to unique names.  All references to the original name will be

            .. versionadded:: 2.0

- **paste_transfer(self, mouse_x: 'int', mouse_y: 'int') -> 'bool'** -> `bool`
            Paste a component and its definition from the clipboard,
            so it can be used in this project.

            .. versionchanged:: 2.0
- **``Component.copy_transfer()`` is deprecated; simply**
- **:meth:`.Canvas.copy()` the component(s) to the smart clipboard.**

- **selector = _get_by_last_id(self, *iid)** `@deprecated`

- **slider = _get_by_last_id(self, *iid)** `@deprecated`

- **switch = _get_by_last_id(self, *iid)** `@deprecated`

- **tline = user_cmp(self, iid)** `@deprecated`

- **user_cmp(self, iid)** `@deprecated`

        ----------------------------------------------------------------------
        Readonly properties defined here:

        definition
            The definition which this canvas belongs to.

            .. versionadded:: 3.0.9

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Canvas:

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

- **create_component(**
            self,
            defn: 'Union[str, Definition]',
            x: 'int' = 1,
            y: 'int' = 1,
            orient: 'int' = 0,
            **parameters
        ) -> 'Component'
            Create a new component and add it to the canvas.

            Parameters:
- **defn (Union[str, Definition]): Type of component to create**
- **x (int): X location of the component (in grid units).**
- **y (int): Y location of the component (in grid units).**
- **orient (int): Rotation/mirroring of the component**
                parameters: key=value pairs

            Returns:
                The created :class:`.Component`.

            .. versionadded:: 2.0

            .. versionchanged:: 2.2
                ``defn`` accepts a :class:`.Definition` or a string.

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
- **definition (str): One of "Bus", "TLine", "Cable", "GraphFrame",** `@property` -> `Definition`
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
        Readonly properties inherited from Canvas:

        name
- **The name of the definition (read-only)** `@property` -> `Definition`

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

## FUNCTIONS
    warn(message, category=None, stacklevel=1, source=None, *,
         skip_file_prefixes=<unrepresentable>)
        Issue a warning, or maybe ignore it or raise an exception.

        message
          Text of the warning message.
        category
          The Warning category subclass. Defaults to UserWarning.
        stacklevel
          How far up the call stack to make this warning appear. A value of 2 for
          example attributes the warning to the caller of the code calling warn().
        source
          If supplied, the destroyed object which emitted a ResourceWarning
        skip_file_prefixes
          An optional tuple of module filename prefixes indicating frames to skip
          during stacklevel computations for stack frame attribution.

## DATA
    Iterator = typing.Iterator
        A generic version of collections.abc.Iterator.

    LOG = <Logger mhi.pscad.canvas (INFO)>
    List = typing.List
        A generic version of list.

    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    RES_ID = {'GRAPHS_COPYDATA_ALL': 901, 'GRAPHS_COPYDATA_VIS': 900, 'GRA...
    Sequence = typing.Sequence
        A generic version of collections.abc.Sequence.

    Set = typing.Set
        A generic version of set.

    TYPE_CHECKING = False
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
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/canvas.py
