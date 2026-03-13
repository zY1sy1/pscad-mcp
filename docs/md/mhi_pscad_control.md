# Module mhi.pscad.control

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/control.py*

Python Library Documentation: module mhi.pscad.control in mhi.pscad

## NAME
    mhi.pscad.control

## DESCRIPTION
    ==================
    Control Components
    ==================

## CLASSES
    mhi.pscad.component.Component(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin)
        Control
            Button
            Selector
            Slider
            Switch
    mhi.pscad.graph.ZFrame(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
        ControlFrame

### class Button(Control)
- **Button(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A momentary contact control.

        A button will output the ``Min`` value until the user clicks the
        button, at which point it will output ``Max`` for one time-step,
        and then resume outputing ``Min``:

        .. table:: Button-specific Properties

           ============ ===== ============================================
           Param Name   Type  Description
           ============ ===== ============================================
           Min          float Button's output value when not pressed
           Max          float Button's output value when pressed
           ============ ===== ============================================

        Method resolution order:
            Button
            Control
            mhi.pscad.component.Component
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **click(self) -> 'None'** -> `None`
            Press and release the button

- **press(self) -> 'None'** -> `None`
            Press the button

- **release(self) -> 'None'** -> `None`
            Release the button

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Control:

- **__getitem__(self, key: 'str')**

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **reset(self) -> 'None'**
            Reset the control component

- **set_value(self, **kwargs)**

        ----------------------------------------------------------------------
        Readonly properties inherited from Control:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Control:

        order
            Position in Control Panel

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

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

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

### class Control(mhi.pscad.component.Component)
- **Control(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Input controls allow the user to make changes to a simulation before or
        during a run, by varying set-points, or switching inputs on or off.

        Method resolution order:
            Control
            mhi.pscad.component.Component
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **__getitem__(self, key: 'str')**

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)** -> `Optional[Parameters]`
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **range(self, parameter: 'str') -> 'ParameterRange'** -> `ParameterRange`
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **reset(self) -> 'None'** `@rmi` -> `None`
            Reset the control component

- **set_value(self, **kwargs)** `@deprecated`

        ----------------------------------------------------------------------
        Readonly properties defined here:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors defined here:

        order
            Position in Control Panel

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

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

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

### class ControlFrame(mhi.pscad.graph.ZFrame)
- **ControlFrame(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A container for holding buttons, switches, and dials

        Method resolution order:
            ControlFrame
            mhi.pscad.graph.ZFrame
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Methods defined here:

- **create_control(self, control_component: 'Component') -> 'Control'** `@rmi` -> `Control`
            Create control in the control frame connected to the given control
            component.

            The control component must be one of the following:

            * ``master:var``,
            * ``master:var_button``,
            * ``master:var_switch``, or a
            * ``master:var_dial``

            Parameters:
- **control_component (Component): the control component**

            Returns:
                Control: the created control

- **create_controls(self, *control_components: 'Component') -> 'List[Control]'** -> `List[Control]`
            Create several controls in the control frame connected to the given
            control components.

            The control components must each be one of:

            * ``master:var``,
            * ``master:var_button``,
            * ``master:var_switch``, or a
            * ``master:var_dial``

            Parameters:
- ***control_components (Component): A list of control components**

            Returns:
                List[Control]: the created controls

- **reset(self) -> 'None'** `@rmi` -> `None`
            Reset all controls in the control frame

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.graph.ZFrame:

- **minimize(self, flag: 'bool' = True) -> 'None'**
            Minimize the frame.

- **restore(self) -> 'None'**
            Restore the frame from its minimized state.

- **toggle_minimize(self) -> 'None'**
            Toggle minimized/restored state

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.graph.ZFrame:

        title
            The title displayed on the frame

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

### class Selector(Control)
- **Selector(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A multi-state switch having between 3 and 10 states.  Also known as
        a "Dial" or a "Rotary Switch".

        .. table:: Selector-specific Properties

           ============ ===== ============================================
           Param Name   Type  Description
           ============ ===== ============================================
- **NDP          int   # of dial positions (3 - 10)**
- **Value        int   Initial dial position (1 - NDP)** -> `None`
- **conv         str   Convert output to the nearest integer (``"YES"`` or ``"NO"``)**
           LabelType    str   Appearence.  ``"INDEX"``, ``"INDEX_AND_VALUE"`` or  ``"VALUE"``
           F1           float Output value for position #1
           F2           float Output value for position #2
           F3           float Output value for position #3
           F4           float Output value for position #4
           F5           float Output value for position #5
           F6           float Output value for position #6
           F7           float Output value for position #7
           F8           float Output value for position #8
           F9           float Output value for position #9
           F10          float Output value for position #10
           ============ ===== ============================================

        Method resolution order:
            Selector
            Control
            mhi.pscad.component.Component
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **position(self, position: 'int') -> 'None'** -> `None`
            Set the selector to the given position

            Parameters:
- **position (int): Desired dial position (1 to NDP)** -> `None`

- **value(self, position: 'int') -> 'None'** `@deprecated` -> `None`

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Control:

- **__getitem__(self, key: 'str')**

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **reset(self) -> 'None'**
            Reset the control component

- **set_value(self, **kwargs)**

        ----------------------------------------------------------------------
        Readonly properties inherited from Control:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Control:

        order
            Position in Control Panel

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

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

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

### class Slider(Control)
- **Slider(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A variable input between minumum & maximum values.

        .. table:: Button-specific Properties

           ============ ===== ============================================
           Param Name   Type  Description
           ============ ===== ============================================
           Max          float Slider's maximum value
           Min          float Slider's minimum value
           Value        float Slider's initial value
           Units        str   Units to display on slider control
- **Collect      str   Data collection (``"CONTINUOUS"`` or ``"ON_RELEASE"``)**
           ============ ===== ============================================

        Method resolution order:
            Slider
            Control
            mhi.pscad.component.Component
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **limits(self, lower: 'float', upper: 'float') -> 'None'** -> `None`
            Set slider minumum and maximum limits

            Parameters:
- **lower (float): Lower limit for slider**
- **upper (float): Upper limit for slider**

- **value(self, value: 'float') -> 'None'** -> `None`
            Set the slider to the given value

            Parameters:
- **value (float): Slider position value** -> `None`

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Control:

- **__getitem__(self, key: 'str')**

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **reset(self) -> 'None'**
            Reset the control component

- **set_value(self, **kwargs)**

        ----------------------------------------------------------------------
        Readonly properties inherited from Control:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Control:

        order
            Position in Control Panel

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

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

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

### class Switch(Control)
- **Switch(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A switch will output one of two values, depending on the position
        of the switch control:

        .. table:: Switch-specific Properties

           ============ ===== ============================================
           Param Name   Type  Description
           ============ ===== ============================================
           Max          float Output value in the "On" position
           Min          float Output value in the "Off" position
           Ton          str   Text label for the "On" position
           Toff         str   Text label for the "Off" position
- **Value        str   Initial State (``"ON"`` or ``"OFF"``)**
- **conv         str   Convert output to the nearest integer (``"YES"`` or ``"NO"``)**
           ============ ===== ============================================

        Method resolution order:
            Switch
            Control
            mhi.pscad.component.Component
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            builtins.object

        Methods defined here:

- **off(self) -> 'None'** -> `None`
            Turn the switch to the Off state

- **on(self) -> 'None'** -> `None`
            Turn the switch to the On state

- **set_state(self, state: 'bool') -> 'None'** -> `None`
            Set the switch to the indicated state

            Parameters:
- **state (bool): ``True`` = On, ``False`` = Off**

- **value(self, position: 'int') -> 'None'** `@deprecated` -> `None`

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Control:

- **__getitem__(self, key: 'str')**

- **parameters(self, *, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'**
            Set or get the component's parameters.

            Parameters:
- **parameters (dict): A dictionary of parameter values. (optional)**
                **kwargs: name=value keyword parameters.

            Returns:
- **A dictionary of parameter values (if no parameters are being set),**
                or None.

- **range(self, parameter: 'str') -> 'ParameterRange'**
            Get legal values for a parameter

            Parameters:
- **parameter (str): A component parameter name**

            Returns:
                * a ``tuple``, or ``frozenset`` of legal values, or
- *** a ``range`` of legal values (integer setttings only), or**
                * a ``Tuple[float, float]`` defining minimum & maximum values, or
                * an exception if the parameter does not have a defined range.

- **reset(self) -> 'None'**
            Reset the control component

- **set_value(self, **kwargs)**

        ----------------------------------------------------------------------
        Readonly properties inherited from Control:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Control:

        order
            Position in Control Panel

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

- **project(self) -> 'Project'**
            The project this component exists in

            :type: Project

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
- **Canvas this component is located on (read-only)** -> `None`

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
    LOG = <Logger mhi.pscad.control (INFO)>
    List = typing.List
        A generic version of list.

    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    TYPE_CHECKING = False

## FILE
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/control.py
