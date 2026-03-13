# Module mhi.pscad.annotation

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/annotation.py*

Python Library Documentation: module mhi.pscad.annotation in mhi.pscad

## NAME
    mhi.pscad.annotation

## DESCRIPTION
    ===========
    Annotations
    ===========

## CLASSES
    mhi.pscad.component.Component(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin)
        Divider
    mhi.pscad.component.MovableMixin(builtins.object)
        GroupBox(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
        Sticky(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
    mhi.pscad.component.SizeableMixin(builtins.object)
        GroupBox(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
        Sticky(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
    mhi.pscad.component.ZComponent(mhi.pscad.remote.Remotable)
        GroupBox(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
        Sticky(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)

### class Divider(mhi.pscad.component.Component)
- **Divider(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A variable length horizontal or vertical divider that can be added to
        a user canvas.

        .. table:: Divider Settings

           ============== ====== ===================================================
           Param Name     Type   Description
           ============== ====== ===================================================
           state          Choice Display: 2D, 3D
           true-color     Color  Colour
           style          Choice Line Style: SOLID, DASH, DOT, DASHDOT
           weight         Choice Line Weight: 02_PT, 04_PT, 06_PT, 08_PT, 10_PT,                              12_PT, 14_PT
           ============== ====== ===================================================

        Method resolution order:
            Divider
            mhi.pscad.component.Component
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **dashed(**
            self,
            weight: Union[str, int, float, NoneType] = None,
            colour: Optional[str] = None
        )
            Set the divider to a non-3D appearence, with a dashed line style.
            Optionally, change the line weight and colour.

            Parameters:
- **weight: the divider's line weight. (optional)**
- **colour (str): The divider's line colour. (optional)**

- **dot_dash(**
            self,
            weight: Union[str, int, float, NoneType] = None,
            colour: Optional[str] = None
        )
            Set the divider to a non-3D appearence, with a dot-dash line style.
            Optionally, change the line weight and colour.

            Parameters:
- **weight: the divider's line weight. (optional)**
- **colour (str): The divider's line colour. (optional)**

- **dotted(**
            self,
            weight: Union[str, int, float, NoneType] = None,
            colour: Optional[str] = None
        )
            Set the divider to a non-3D appearence, with a dotted line style.
            Optionally, change the line weight and colour.

            Parameters:
- **weight: the divider's line weight. (optional)**
- **colour (str): The divider's line colour. (optional)**

- **flat(** -> `None`
            self,
            style: Optional[str] = None,
            weight: Union[str, int, float, NoneType] = None,
            colour: Optional[str] = None
        ) -> None
            Set the divider to a non-3D appearence.  Optionally,
            change the line style, weight and colour.

            Parameters:
- **style (str): ``SOLID``, ``DASH``, ``DOT``, or ``DASHDOT``. (optional)**
- **weight: the divider's line weight. (optional)**
- **colour (str): The divider's line colour. (optional)**

            The weight can be given as a floating point number, between 0.2 and 1.4,
            and integer between 0 and 7, or a string such as ``"02_PT"``.

- **horizontal(self, width: int)** `@rmi`
            Set the divider to horizontal orientation with the given width.

            Parameters:
- **width (int): the width of the divider, in grid units.**

- **raised(self, colour: Optional[str] = None)**
            Set the divider to a 3D appearence.  Optionally, change the colour.

            Parameters:
- **colour (str): The divider's line colour. (optional)**

- **solid(**
            self,
            weight: Union[str, int, float, NoneType] = None,
            colour: Optional[str] = None
        )
            Set the divider to a non-3D appearence, with a solid line style.
            Optionally, change the line weight and colour.

            Parameters:
- **weight: the divider's line weight. (optional)**
- **colour (str): The divider's line colour. (optional)**

- **vertical(self, height: int)** `@rmi`
            Set the divider to vertical orientation with the given height.

            Parameters:
- **height (int): the height of the divider, in grid units.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.Component:

- **flip(self) -> 'bool'**
            Flip the component along the vertical axis

- **is_module(self) -> 'bool'**
            Check to see if this component has its own canvas, with in turn,
            can contain additional components.

            :class:`Transmission lines <.TLine>`, :class:`cables <.Cable>`,
            and some :class:`user components <.UserCmp>` are modules with
            their own canvas.

            Returns:
                bool: ``True`` if the component has an internal canvas,
                ``False`` otherwise.

- **mirror(self) -> 'bool'**
            Mirror the component along the horizontal axis

- **rotate_180(self) -> 'bool'**
            Rotate the component 90 degrees to the right

- **rotate_left(self) -> 'bool'**
- **Rotate the component 90 degrees to the left (counter-clockwise)**

- **rotate_right(self) -> 'bool'**
- **Rotate the component 90 degrees to the right (clockwise)**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__repr__(self)**
- **Return repr(self).**

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

### class GroupBox(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
- **GroupBox(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A group box which may be placed on a user canvas, to visually show
        components which are related to each other.

        .. table:: Group Box Parameters

           ============= ====== ============================================
           Param Name    Type   Description
           ============= ====== ============================================
           name          str    Name of the group box
           show_name     bool   Show or Hide the group name
           font          Font   Font
           line_style    int    Border style: SOLID, DASH, DOT, DASHDOT
           line_weight   int    Border Weight: 02_PT, 04_PT, 06_PT, 08_PT,                             10_PT, 12_PT, 14_PT
           line_colour   Color  Colour of the group box border
           fill_style    int    Fill style of the group box interior
           fill_fg       Color  Colour of foreground fill
           fill_bg       Color  Colour of background fill
           ============= ====== ============================================

        .. versionadded:: 2.9

        Method resolution order:
            GroupBox
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__repr__(self)**
- **Return repr(self).**

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

### class Sticky(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
- **Sticky(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A text note which may be placed on a user canvas, and which can have
        arrows pointing in up to 8 directions from the sides/corners of
        the Sticky note.

        .. table:: Sticky Note Parameters

           ============= ====== ===========================================
           Param Name    Type   Description
           ============= ====== ===========================================
           full_font     Font   Font
           align         Choice Alignment: LEFT, CENTRE, RIGHT
           fg_color_adv  Color  Text Colour
           bg_color_adv  Color  Background Colour
           bdr_color_adv Color  Border Colour
           ============= ====== ===========================================

        Method resolution order:
            Sticky
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Methods defined here:

- **arrows(** -> `str`
            self,
            *args: str,
- **add: Union[int, str, Sequence[str]] = (),**
- **remove: Union[int, str, Sequence[str]] = ()**
        ) -> str
            Get or set the arrows on the Text Area.

            With no arguments, the current arrows are returned as a string.

            If any positional arguments are given, the arrows are set to the
            indicated directions only.

            If the `add` keyword argument is specified, these arrows
            are added on the text area, joining any existing arrows.

            If the `remove` keyword argument is specified, these arrows
            are removed from the text area.

            The direction arrows may be given as iterable group of strings,
            or as a space-separated string.

            Parameters:
                *args: arrow directions to set on the Text Area
                add: arrow directions to add to the Text Area
                remove: arrow directions to remove from the Text Area

            Returns:
                - a string describing the current arrow configuration

            Examples::

- **note.arrows("N", "NE")  # Set North & North-East arrows only.** -> `str`
- **note.arrows("N NE")     # Set North & North-East arrows only.** -> `str`
- **note.arrows(add="N NE") # Add the North & North-East arrows.** -> `str`
- **note.arrows(remove=("N", "NE")) # Remove those arrows.** -> `str`

        ----------------------------------------------------------------------
        Data descriptors defined here:

        text
            Text in the text area

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.ZComponent:

- **__getitem__(self, key: 'str') -> 'Any'**

- **__repr__(self)**
- **Return repr(self).**

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

## DATA
    Directions = typing.Union[int, str, typing.Sequence[str]]
    LOG = <Logger mhi.pscad.annotation (INFO)>
    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    Sequence = typing.Sequence
        A generic version of collections.abc.Sequence.

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

    Weight = typing.Union[str, int, float, NoneType]

## FILE
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/annotation.py
