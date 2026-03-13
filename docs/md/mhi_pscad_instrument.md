# Module mhi.pscad.instrument

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/instrument.py*

Python Library Documentation: module mhi.pscad.instrument in mhi.pscad

## NAME
    mhi.pscad.instrument

## DESCRIPTION
    ================
    Instruments
    ================

## CLASSES
    mhi.pscad.graph.ZFrame(mhi.pscad.component.ZComponent, mhi.pscad.component.MovableMixin, mhi.pscad.component.SizeableMixin)
        Instrument
            Oscilloscope
            PhasorMeter
            PolyMeter

### class Instrument(mhi.pscad.graph.ZFrame)
- **Instrument(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Output controls allowing the user to observe quantities changing during
        a simulation.

        Includes Oscilloscopes, Phasor Meters and Poly Meters.

        Method resolution order:
            Instrument
            mhi.pscad.graph.ZFrame
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Methods defined here:

- **__getitem__(self, key)**

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

        ----------------------------------------------------------------------
        Readonly properties defined here:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors defined here:

        title
            The title displayed on the frame

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

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.SizeableMixin:

- **get_size(self) -> 'Tuple[int, int]'**

- **set_size(self, width: 'int', height: 'int') -> 'None'**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.SizeableMixin:

        size
            Set/get width & height of a sizeable component

### class Oscilloscope(Instrument)
- **Oscilloscope(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        An Oscilloscope is a special runtime object that is used to mimic the
        triggering effects of a real-world oscilloscope on a time varying,
        cyclical signal like an AC voltage or current.
        Given a base frequency, the oscilloscope will follow the signal during
- **a simulation (like a moving window), refreshing its display at the rate**
        given by the base frequency.
        This gives the illusion that the oscilloscope is transfixed on the signals
        being displayed, resulting in a triggering effect.

        Method resolution order:
            Oscilloscope
            Instrument
            mhi.pscad.graph.ZFrame
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Data descriptors defined here:

        cycles
            Number of cycles to display

        frequency
            Base frequency

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Instrument:

- **__getitem__(self, key)**

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

        ----------------------------------------------------------------------
        Readonly properties inherited from Instrument:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Instrument:

        title
            The title displayed on the frame

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.graph.ZFrame:

- **minimize(self, flag: 'bool' = True) -> 'None'**
            Minimize the frame.

- **restore(self) -> 'None'**
            Restore the frame from its minimized state.

- **toggle_minimize(self) -> 'None'**
            Toggle minimized/restored state

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

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.SizeableMixin:

- **get_size(self) -> 'Tuple[int, int]'**

- **set_size(self, width: 'int', height: 'int') -> 'None'**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.SizeableMixin:

        size
            Set/get width & height of a sizeable component

### class PhasorMeter(Instrument)
- **PhasorMeter(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A PhasorMeter is a special runtime object that can be used to display
        up to six, separate phasor quantities.
        The phasormeter displays phasors in a polar graph, where the magnitude and
        phase of each phasor responds dynamically during a simulation run.
        This device is perfect for visually representing phasor quantities,
- **such as output from the Fast Fourier Transform (FFT) component.**

        Method resolution order:
            PhasorMeter
            Instrument
            mhi.pscad.graph.ZFrame
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Readonly properties defined here:

        index
- **Active phasor index (read-only)** `@rmi_property` -> `int`

            :type: int

        ----------------------------------------------------------------------
        Data descriptors defined here:

        degrees
            True if Phasor Meter angle input is in degrees

        radians
            True if Phasor Meter angle input is in radians

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Instrument:

- **__getitem__(self, key)**

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

        ----------------------------------------------------------------------
        Readonly properties inherited from Instrument:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Instrument:

        title
            The title displayed on the frame

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.graph.ZFrame:

- **minimize(self, flag: 'bool' = True) -> 'None'**
            Minimize the frame.

- **restore(self) -> 'None'**
            Restore the frame from its minimized state.

- **toggle_minimize(self) -> 'None'**
            Toggle minimized/restored state

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

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.SizeableMixin:

- **get_size(self) -> 'Tuple[int, int]'**

- **set_size(self, width: 'int', height: 'int') -> 'None'**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.SizeableMixin:

        size
            Set/get width & height of a sizeable component

### class PolyMeter(Instrument)
- **PolyMeter(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        A polymeter is a special runtime object used specifically for monitoring
        a single, multiple-trace curve.
        The polymeter dynamically displays the magnitude of each trace in
- **bar type format (called gauges),**
        which results in an overall appearance similar to a spectrum analyzer.
        The power of this device lies in its ability to compress a large amount
        of data into a small viewing area, which is particularly helpful when
        viewing harmonic spectrums such as data output from the Fast Fourier
- **Transform (FFT) component.**

        Method resolution order:
            PolyMeter
            Instrument
            mhi.pscad.graph.ZFrame
            mhi.pscad.component.ZComponent
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            mhi.pscad.component.MovableMixin
            mhi.pscad.component.SizeableMixin
            builtins.object

        Data descriptors defined here:

        color
            Colour of bars in Poly Meter

        colour
            Colour of bars in Poly Meter

        labels
            Meter labels visible?

        scrollable
            Scroll view enabled?

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from Instrument:

- **__getitem__(self, key)**

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

        ----------------------------------------------------------------------
        Readonly properties inherited from Instrument:

        link_id
            Related / linked component id

        linked
            Component which this control component is linked to.

        ----------------------------------------------------------------------
        Data descriptors inherited from Instrument:

        title
            The title displayed on the frame

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.graph.ZFrame:

- **minimize(self, flag: 'bool' = True) -> 'None'**
            Minimize the frame.

- **restore(self) -> 'None'**
            Restore the frame from its minimized state.

- **toggle_minimize(self) -> 'None'**
            Toggle minimized/restored state

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

        ----------------------------------------------------------------------
        Methods inherited from mhi.pscad.component.SizeableMixin:

- **get_size(self) -> 'Tuple[int, int]'**

- **set_size(self, width: 'int', height: 'int') -> 'None'**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.pscad.component.SizeableMixin:

        size
            Set/get width & height of a sizeable component

## DATA
    LOG = <Logger mhi.pscad.instrument (INFO)>
    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    TYPE_CHECKING = False

## FILE
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/instrument.py
