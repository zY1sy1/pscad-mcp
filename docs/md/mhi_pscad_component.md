# Module mhi.pscad.component

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/component.py*

Python Library Documentation: module mhi.pscad.component in mhi.pscad

## NAME
    mhi.pscad.component

## DESCRIPTION
    =========
    Component
    =========

## CLASSES
    builtins.object
        MovableMixin
        SizeableMixin
    mhi.pscad.remote.Remotable(mhi.common.remote.Remotable)
        ZComponent
            Component(ZComponent, MovableMixin)
                UserCmp(Component, ModuleMixin)
                Wire
                    ACLine(Wire, ModuleMixin)
                        Cable
                        TLine
                    Bus
                    StickyWire
            ModuleMixin

### class ACLine(Wire, ModuleMixin)
- **ACLine(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

- **Travelling Wave Model lines (T-Line & Cables)**

        Method resolution order:
            ACLine
            Wire
            Component
            ModuleMixin
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **compile(self) -> 'None'** -> `None`
            Solve the constants for this T-Line/Cable page

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Wire:

- **decompose(self)**
            Break the wire down into deperate wires

- **endpoints(self) -> 'Tuple[Point, Point]'**
            Get the end-points of the wire.  Internal vertices are not returned.

            Returns:
                List[Point]: The wire's end-points

- **vertices(self, *vertices: 'AnyPoint') -> 'List[Point]'**
- **Wire.vertices([vertices])**

            Set or get the vertices of the wire

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ModuleMixin:

- **canvas(self) -> 'Canvas'**
            Get the module's canvas

            Returns:
                :class:`.Canvas` : The canvas containing this module's subcomponents

        ----------------------------------------------------------------------
        Readonly properties inherited from ModuleMixin:

        definition
            Retrieve module definition

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class Bus(Wire)
- **Bus(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Bus Component

        A Bus is a 3-phase electrical :class:`.wire`.
        It addition to :meth:`vertices <.vertices>`,
        it has :meth:`parameters <.UserCmp.parameters>` which can be set and
        retrieved.

- **To construct a new bus, use :meth:`.UserCanvas.create_bus()`.**

        .. table:: Bus Parameters

            =========== ===== ==============================================
            Parameter   Type  Description
            =========== ===== ==============================================
            Name        str   Name of the Bus
            BaseKV      float Bus Base Voltage, in kV. May be zero.
            VA          float Bus Base Angle, in degrees
            VM          float Bus Base Magnitude, in degrees
            type        int   0=Auto, 1=Load, 2=Generator or 3=Swing
            =========== ===== ==============================================

        Method resolution order:
            Bus
            Wire
            Component
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Wire:

- **decompose(self)**
            Break the wire down into deperate wires

- **endpoints(self) -> 'Tuple[Point, Point]'**
            Get the end-points of the wire.  Internal vertices are not returned.

            Returns:
                List[Point]: The wire's end-points

- **vertices(self, *vertices: 'AnyPoint') -> 'List[Point]'**
- **Wire.vertices([vertices])**

            Set or get the vertices of the wire

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class Cable(ACLine)
- **Cable(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Cable Component

        A Cable component is defined by 4 :meth:`vertices <.vertices>`,
        which form a 3 line segments.
        The first and last segments must be horizontal or vertical segments;
        the middle segment may be diagonal.

        It addition to vertices, a cable will also have a collection
        of :meth:`parameters <.UserCmp.parameters>` as well as a
        :meth:`canvas <.UserCmp.canvas>` containing additional components
        defining the cable.

        Method resolution order:
            Cable
            ACLine
            Wire
            Component
            ModuleMixin
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from ACLine:

- **__repr__(self)**
- **Return repr(self).**

- **compile(self) -> 'None'**
            Solve the constants for this T-Line/Cable page

        ----------------------------------------------------------------------
        Methods inherited from Wire:

- **decompose(self)**
            Break the wire down into deperate wires

- **endpoints(self) -> 'Tuple[Point, Point]'**
            Get the end-points of the wire.  Internal vertices are not returned.

            Returns:
                List[Point]: The wire's end-points

- **vertices(self, *vertices: 'AnyPoint') -> 'List[Point]'**
- **Wire.vertices([vertices])**

            Set or get the vertices of the wire

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ModuleMixin:

- **canvas(self) -> 'Canvas'**
            Get the module's canvas

            Returns:
                :class:`.Canvas` : The canvas containing this module's subcomponents

        ----------------------------------------------------------------------
        Readonly properties inherited from ModuleMixin:

        definition
            Retrieve module definition

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class Component(ZComponent, MovableMixin)
- **Component(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Components which can be moved & rotated on a Canvas.
        They might also be modules.

        Method resolution order:
            Component
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Methods defined here:

- **flip(self) -> 'bool'** -> `bool`
            Flip the component along the vertical axis

- **is_module(self) -> 'bool'** `@rmi` -> `bool`
            Check to see if this component has its own canvas, with in turn,
            can contain additional components.

            :class:`Transmission lines <.TLine>`, :class:`cables <.Cable>`,
            and some :class:`user components <.UserCmp>` are modules with
            their own canvas.

            Returns:
                bool: ``True`` if the component has an internal canvas,
                ``False`` otherwise.

- **mirror(self) -> 'bool'** -> `bool`
            Mirror the component along the horizontal axis

- **rotate_180(self) -> 'bool'** -> `bool`
            Rotate the component 90 degrees to the right

- **rotate_left(self) -> 'bool'** -> `bool`
- **Rotate the component 90 degrees to the left (counter-clockwise)**

- **rotate_right(self) -> 'bool'** -> `bool`
- **Rotate the component 90 degrees to the right (clockwise)**

        ----------------------------------------------------------------------
        Data descriptors defined here:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class ModuleMixin(ZComponent)
- **ModuleMixin(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

- **Modules (Components containing a canvas with more components)**

        Method resolution order:
            ModuleMixin
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **canvas(self) -> 'Canvas'** -> `Canvas`
            Get the module's canvas

            Returns:
                :class:`.Canvas` : The canvas containing this module's subcomponents

        ----------------------------------------------------------------------
        Readonly properties defined here:

        definition
            Retrieve module definition

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
- **The name of the definition (read-only)** `@property` -> `Definition`

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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

### class MovableMixin(builtins.object)
        Things that may be moved

        Methods defined here:

- **copy(self) -> 'bool'** -> `bool`
            Copy this component to the clipboard.

- **cut(self) -> 'bool'** -> `bool`
            Cut this component to the clipboard

- **delete(self) -> 'bool'** -> `bool`
            Delete this component.

- **get_location(self)** `@deprecated`
- **Get this component's (x,y) location**

            Returns:
                Tuple[int, int]: The x,y location of the component, in grid units

- **set_location(self, x, y)** `@deprecated`
- **Set the component's (x,y) location**

            Parameters:
- **x (int): The new x location for this component**
- **y (int): The new y location for this component**

        ----------------------------------------------------------------------
        Readonly properties defined here:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

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
        Data and other attributes defined here:

        __annotations__ = {}

### class SizeableMixin(builtins.object)
        Things that can be resized

        Methods defined here:

- **get_size(self) -> 'Tuple[int, int]'** `@deprecated` -> `Tuple[int, int]`

- **set_size(self, width: 'int', height: 'int') -> 'None'** `@deprecated` -> `None`

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        size
            Set/get width & height of a sizeable component

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

### class StickyWire(Wire)
- **StickyWire(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A "Sticky Wire" is an electrical wire or control signal,
        which stretches to maintain connection to a component it is attached to.

        Unlike all other wires, a "Sticky Wire" may have more than two end-points.
        Each pair of vertices form a horizontal or vertical line segment,
        which is then attached to a central point by diagonal line segments.

- **To construct a new sticky wire, use :meth:`.UserCanvas.create_sticky_wire()`.**

        Method resolution order:
            StickyWire
            Wire
            Component
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Wire:

- **__repr__(self)**
- **Return repr(self).**

- **decompose(self)**
            Break the wire down into deperate wires

- **endpoints(self) -> 'Tuple[Point, Point]'**
            Get the end-points of the wire.  Internal vertices are not returned.

            Returns:
                List[Point]: The wire's end-points

- **vertices(self, *vertices: 'AnyPoint') -> 'List[Point]'**
- **Wire.vertices([vertices])**

            Set or get the vertices of the wire

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class TLine(ACLine)
- **TLine(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Transmission Line Component

        A Transmission Line component is defined by 4 :meth:`vertices <.vertices>`,
        which form a 3 line segments.
        The first and last segments must be horizontal or vertical segments;
        the middle segment may be diagonal.

        It addition to vertices, a transmission line will also have a collection
        of :meth:`parameters <.UserCmp.parameters>` as well as a
        :meth:`canvas <.UserCmp.canvas>` containing additional components
        defining the transmission line.

        Method resolution order:
            TLine
            ACLine
            Wire
            Component
            ModuleMixin
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from ACLine:

- **__repr__(self)**
- **Return repr(self).**

- **compile(self) -> 'None'**
            Solve the constants for this T-Line/Cable page

        ----------------------------------------------------------------------
        Methods inherited from Wire:

- **decompose(self)**
            Break the wire down into deperate wires

- **endpoints(self) -> 'Tuple[Point, Point]'**
            Get the end-points of the wire.  Internal vertices are not returned.

            Returns:
                List[Point]: The wire's end-points

- **vertices(self, *vertices: 'AnyPoint') -> 'List[Point]'**
- **Wire.vertices([vertices])**

            Set or get the vertices of the wire

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)**

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ModuleMixin:

- **canvas(self) -> 'Canvas'**
            Get the module's canvas

            Returns:
                :class:`.Canvas` : The canvas containing this module's subcomponents

        ----------------------------------------------------------------------
        Readonly properties inherited from ModuleMixin:

        definition
            Retrieve module definition

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class UserCmp(Component, ModuleMixin)
- **UserCmp(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

- **Non-builtin components (a.k.a User Components)**

        Method resolution order:
            UserCmp
            Component
            ModuleMixin
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **blackbox(** -> `Component`
            self,
            x: 'Optional[int]' = None,
            y: 'Optional[int]' = None,
            sub_prefix: 'Optional[str]' = None,
            instance_data: 'Optional[bool]' = None
        ) -> 'Component'
            Convert this component page into a blackboxed module

            .. versionchanged:: 2.7
                Added ``x``, ``y``, ``sub_prefix`` & ``instance_data`` parameters.

- **blackbox_defn(self) -> 'Definition'** `@requires` -> `Definition`
            Convert this component page into a blackboxed module definition

            .. versionadded:: 2.7

- **compile(self) -> 'None'** -> `None`
            Compile this component page

- **copy_transfer(self)** `@deprecated`

- **get_definition(self)** `@deprecated`

- **get_parameters(self, scenario: 'Optional[str]' = None) -> 'Parameters'** `@deprecated` -> `Parameters`
            Get the component's parameters.

            The parameters contained in the component are determined by the
            component definition.

            Parameters:
- **scenario (str): Name of scenario to get parameters from. (optional)**

            Returns:
                A dictionary of parameter name="value" pairs.

- **get_port_location(self, name)** `@deprecated`

- **navigate_in(self) -> 'Canvas'** -> `Canvas`
            Navigate into a page module or definition

- **parameters(** -> `Optional[Parameters]`
            self,
            scenario: 'Optional[str]' = None,
            *,
            parameters: 'Optional[Parameters]' = None,
            **kwargs
        ) -> 'Optional[Parameters]'
            Set or get the component's parameters.

            Parameters:
- **scenario (str): Name of scenario to set parameters for. (optional)**
- **parameters (dict): A dictionary of parameter values. (optional)** -> `Optional[Parameters]`
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **port(self, name: 'str') -> 'Optional[Port]'** -> `Optional[Port]`
            Based on the location of this component, taking into account any
            any rotation and/or mirroring, return the location and type of the
            named component port.

            Returns:
                tuple: The x, y location, name, dimension and type of the port.

- **ports(self) -> 'Dict[str, Port]'** -> `Dict[str, Port]`
            Retrieve the active ports of a component.

            Returns:
                Dict[str, Port]: A dictionary of ports, by port name.

- **set_parameters(self, scenario: 'Optional[str]' = None, **kwargs) -> 'None'** `@deprecated` -> `None`
- **set_parameters([scenario], name=value [, ...])** `@deprecated` -> `None`
            Set the component's parameters.

            Parameters:
- **scenario (str): Name of scenario to set parameters for. (optional)**
                **kwargs: One or more name=value keyword parameters

            All parameters are converted to strings.  No checks are made to
            determine if a value is valid or not.

- **view_ParameterGrid(self)** `@deprecated`

        ----------------------------------------------------------------------
        Data descriptors defined here:

        definition
            The User Component's definition

        sequence
            Component Sequence Number

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {'_form_codecs': 'Dict[str, FormCodec]'}

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ModuleMixin:

- **canvas(self) -> 'Canvas'**
            Get the module's canvas

            Returns:
                :class:`.Canvas` : The canvas containing this module's subcomponents

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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

- **import_parameters(self, csvfile: 'str') -> 'None'**
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class Wire(Component)
- **Wire(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        An electrical wire or control signal.

        Wires are continuous lines which connect 2 or more vertices.
        Each segment must be horizontal or vertical.

- **To construct a new wire, use :meth:`.UserCanvas.create_wire()`.**

        Method resolution order:
            Wire
            Component
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            MovableMixin
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **decompose(self)**
            Break the wire down into deperate wires

- **endpoints(self) -> 'Tuple[Point, Point]'** -> `Tuple[Point, Point]`
            Get the end-points of the wire.  Internal vertices are not returned.

            Returns:
                List[Point]: The wire's end-points

- **vertices(self, *vertices: 'AnyPoint') -> 'List[Point]'** -> `List[Point]`
- **Wire.vertices([vertices])** -> `List[Point]`

            Set or get the vertices of the wire

            Parameters:
- **vertices (List[x,y]): a list of (x,y) coordinates (optional)** -> `List[Point]`

            Returns:
- **List[x,y]: A list of (x,y) coordinates.**

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Component:

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
        Data descriptors inherited from Component:

        orient
            Set/get orientation of an orientable component

        ----------------------------------------------------------------------
        Methods inherited from ZComponent:

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
        Readonly properties inherited from ZComponent:

        iid
- **The id of the component in the project (read-only)**

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors inherited from ZComponent:

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
        Methods inherited from MovableMixin:

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
        Readonly properties inherited from MovableMixin:

        parent
- **Canvas this component is located on (read-only)**

            :type: Canvas

        ----------------------------------------------------------------------
        Data descriptors inherited from MovableMixin:

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

### class ZComponent(mhi.pscad.remote.Remotable)
- **ZComponent(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        All ZSLibrary components

        Method resolution order:
            ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__getitem__(self, key: 'str') -> 'Any'** -> `Any`

- **__repr__(self)**
- **Return repr(self).**

- **__setitem__(self, key: 'str', value: 'Any') -> 'None'** -> `None`

- **add_to_layer(self, name: 'str') -> 'None'** -> `None`
            Add this component to the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to add the component to.**

- **clone(self, x: 'int', y: 'int') -> 'Component'** -> `Component`
            Copy this component and place the copy at the given location.

            Parameters:
- **x (int): x-coordinate for the cloned component (in grid units)**
- **y (int): y-coordinate for the cloned component (in grid units)**

            Returns:
                Component: the cloned component

- **command(self, cmd_name)**

- **custom_state(self, state_name: 'str', state: 'str') -> 'None'** -> `None`
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

- **disable(self) -> 'None'** -> `None`
            Disable this component.

            This component will be disabled regardless of the layer states.
            To re-enable this component use the :meth:`.enable` function.

- **enable(self, enable: 'bool' = True) -> 'None'** -> `None`
            Enable this component.

            With no argument, or if given a `True` value, this will enable a
            disabled component.  If the component is disabled via layers it will
            remain disabled.

            Parameters:
- **enable (bool): If set to `False`, disables the component (optional)** -> `None`

- **export_parameters(self, csvfile: 'str') -> 'None'** -> `None`
            Export component parameters to a CSV file

            Write component parameters to a two-line CSV file.
            The first row will contains the parameter names and the second row
            will contain the parameter values.
            The first column contains the component identifier and the
            parameter name will be blank.

- **get_parameters(self)** `@deprecated`

- **import_parameters(self, csvfile: 'str') -> 'None'** -> `None`
            Import component parameters from a CSV file

            Read component parameters from a two-line CSV file,
            where the first row contains the parameter names and the second row
            contains the parameter values.  The first column represents the
            component identifier and the parameter name must be blank.

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)** -> `Optional[Parameters]`
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **project(self) -> 'Project'** -> `Project`
            The project this component exists in

            :type: Project

- **range(self, parameter: 'str') -> 'ParameterRange'** -> `ParameterRange`
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **remove_from_layer(self, name: 'str') -> 'None'** -> `None`
            Remove this component from the given layer.

            The layer must exist, but need not be enabled or visible.

            Parameters:
- **name (str): The layer to remove the component from.**

- **set_parameters(self, **parameters)** `@deprecated`

- **to_back(self) -> 'bool'** -> `bool`
- **Put at the start (back) of the Z-Order on the canvas.**

- **to_front(self) -> 'bool'** -> `bool`
- **Put at the front (end) of the Z-Order on the canvas.**

- **to_next(self) -> 'bool'** -> `bool`
            Move the component one position forward in the Z-Order relative to the
            current Z-Order position.

- **to_prev(self) -> 'bool'** -> `bool`
            Move the component one position backward in the Z-Order relative to the current
            current Z-Order position.

- **view_parameter_grid(self) -> 'bool'** -> `bool`
            View the parameter grid for this component

        ----------------------------------------------------------------------
        Readonly properties defined here:

        iid
- **The id of the component in the project (read-only)** -> `Project`

            :type: int

        project_name
- **The name of the project this component exists in (read-only)**

            :type: str

        ----------------------------------------------------------------------
        Data descriptors defined here:

        enabled
            The component's enable/disable status.

            This is independent of whether the component is on a layer that is enabled or disabled.

            .. versionadded:: 2.8.1

        layer
            The layer the component is on

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

## DATA
    AnyPoint = typing.Union[mhi.pscad.types.Point, mhi.pscad.types.Port, t...
    Dict = typing.Dict
        A generic version of dict.

    LOG = <Logger mhi.pscad.component (INFO)>
    List = typing.List
        A generic version of list.

    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    PGB = mhi.pscad.component.PGB
    ParameterRange = typing.Union[typing.Tuple, typing.Set, range, NoneTyp...
    Parameters = typing.Dict[str, typing.Any]
    RES_ID = {'GRAPHS_COPYDATA_ALL': 901, 'GRAPHS_COPYDATA_VIS': 900, 'GRA...
    TYPE_CHECKING = False
    Tuple = typing.Tuple
        Deprecated alias to builtins.tuple.

        Tuple[X, Y] is the cross-product type of X and Y.

        Example: Tuple[T1, T2] is a tuple of two elements corresponding
        to type variables T1 and T2.  Tuple[int, float, str] is a tuple
        of an int, a float and a string.

        To specify a variable-length tuple of homogeneous type, use Tuple[T, ...].

## FILE
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/component.py
