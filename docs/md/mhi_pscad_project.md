# Module mhi.pscad.project

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/project.py*

Python Library Documentation: module mhi.pscad.project in mhi.pscad

## NAME
    mhi.pscad.project - The PSCAD Project Proxy Object

## CLASSES
    builtins.object
        GlobalSubstitution
    mhi.pscad.remote.Remotable(mhi.common.remote.Remotable)
        Layer
        Project
        Resource

### class GlobalSubstitution(builtins.object)
- **GlobalSubstitution(project: 'Project')**

        Management for a project's global substitutions and sets of global
        substitutions.

        Returned by :attr:`.Project.global_substitution`

        Methods defined here:

- **__delitem__(self, set_name)**

- **__getitem__(self, set_name)**

- **__init__(self, project: 'Project')**
- **Initialize self.  See help(type(self)) for accurate signature.**

- **__iter__(self)**

- **__len__(self)**

- **__setitem__(self, set_name, values)**

- **append_all_sets(self, filename: 'str') -> 'None'** `@requires` -> `None`
            Load global substitution sets from a CSV file, creating new sets when
            a set name already exists.

            Parameters:
- **filename (str): Filename of the CSV file**

            .. versionadded:: 2.8.1

- **append_set(self, filename: 'str', set_name: 'Optional[str]' = None) -> 'None'** `@requires` -> `None`
            Load global substitution set from a CSV file, without clear old values

            Parameters:
- **filename (str): Filename of the CSV file**
- **set_name (str): Set name to load (default is currently active set)**

            .. versionadded:: 2.8.1

- **create(self, *val_names: 'str') -> 'None'** -> `None`
            Creates 1 or more named global substitution variables.

            Parameters:
- ***val_names (str): One or more new variable names**

- **create_sets(self, *set_names: 'str') -> 'None'** -> `None`
            Creates 1 or more named global substitution sets

            Parameters:
- ***set_names (str): One or more names for the new sets**

- **load_all_sets(self, filename: 'str') -> 'None'** `@requires` -> `None`
            Load all global substitution sets from a CSV file, replacing all
            current values.

            Parameters:
- **filename (str): Filename of the CSV file**

            .. versionadded:: 2.8.1

- **load_set(self, filename: 'str', set_name: 'Optional[str]' = None) -> 'None'** `@requires` -> `None`
            Load global substitution set from a CSV file, replacing current values

            Parameters:
- **filename (str): Filename of the CSV file**
- **set_name (str): Set name to load (default is currently active set)**

            .. versionadded:: 2.8.1

- **remove(self, *val_names: 'str') -> 'None'** -> `None`
            Removes 1 or more named global substitution variables

            Parameters:
- ***val_names (str): One or more names of variables to be deleted**

- **remove_sets(self, *set_names: 'str') -> 'None'** -> `None`
            Removes 1 or more named global substitution sets

            Parameters:
- ***set_names (str): One or more names of sets to be deleted**

- **rename(self, old_name: 'str', new_name: 'str') -> 'bool'** -> `bool`
            Rename a global substitution variable

            Parameters:
- **old_name (str): Current name of the substitution variable**
- **new_name (str): Desired name of the substitution variable**

- **rename_set(self, old_name: 'str', new_name: 'str') -> 'bool'** -> `bool`
            Rename a global substitution set

            Parameters:
- **old_name (str): Current name of the substitution set**
- **new_name (str): Desired name of the substitution set**

- **save_all_sets(self, filename: 'str') -> 'None'** `@requires` -> `None`
            Save all global substitution sets to a CSV file.

            Parameters:
- **filename (str): Filename for the CSV file**

            .. versionadded:: 2.8.1

- **save_set(self, filename: 'str', set_name: 'Optional[str]' = None) -> 'None'** `@requires` -> `None`
            Save global substitution set to a CSV file.

            Parameters:
- **filename (str): Filename for the CSV file**
- **set_name (str): Set name to save (default is currently active set)**

            .. versionadded:: 2.8.1

        ----------------------------------------------------------------------
        Readonly properties defined here:

        main
            The PSCAD application object

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        active_set
            The currently active global substitution set.

            Returns the name of the currently active substitution set,
            or `None` for the default set

            Set to the desired global substitution set name to change
            the active global substitution set.
            Setting this to ``""`` or ``None`` reverts to the default set.

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        Set = <class 'mhi.pscad.project.GlobalSubstitution.Set'>
            Global Substitute Set

### class Layer(mhi.pscad.remote.Remotable)
- **Layer(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Project Component Layer

        Method resolution order:
            Layer
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **add(self, *components: 'Component')**
            Add one or more components to this layer

- **add_state(self, new_name: 'str') -> 'None'** -> `None`
            Create a new custom configuration name for list layer

            Parameters:
- **new_name (str): Name of the new configuration to create.**

- **move_down(self, delta: 'int' = 1) -> 'None'** -> `None`
            Move the layer down the list by 1

- **move_up(self, delta: 'int' = 1) -> 'None'** -> `None`
            Move the layer up the list by 1

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Get or set layer parameters

            Parameters:
- **parameters (dict): A dictionary of name=value parameters** -> `Optional[Parameters]`
                **kwargs: Zero or more name=value keyword parameters

            Returns:
                A dictionary of current parameters, if no parameters were given.


            .. table:: Layer Properties

               ================= ===== ============================================
               Param Name        Type  Description
               ================= ===== ============================================
               disabled_color    Color Disabled Colour
               disabled_opacity  int   Diabled Opacity
               highlight_color   Color Highlight Colour
               highlight_opacity int   Highlight Opacity
               ================= ===== ============================================

- **remove_state(self, state_name: 'str') -> 'None'** -> `None`
            Remove an existing custom state from this layer

            Parameters:
- **state_name (str): The name of the custom configuration state to remove.**

- **rename_state(self, old_name: 'str', new_name: 'str') -> 'None'** -> `None`
            Rename an existing custom state in this layer

            Parameters:
- **old_name (str): The name of the custom configuration state to rename.**
- **new_name (str): The new name to rename the custom configuration state to.**

- **set_custom_state(** -> `None`
            self,
            state_name: 'str',
            component: 'Component',
            component_state: 'str'
        ) -> 'None'
            Set the state of a component when the layer is set to the state name provided.

            Parameters:
- **state_name (str): The name of the custom configuration state to configure.**
- **component  (Component): The component to set the state to**
- **component_state (str): One of the strings ('Enabled', 'Disabled', 'Invisible')                 for the state of the provided component when the provided state is set.**

- **to_bottom(self) -> 'None'** -> `None`
            Move the layer to bottom of list

- **to_top(self) -> 'None'** -> `None`
            Move the layer to top of list

        ----------------------------------------------------------------------
        Readonly properties defined here:

        id
- **The ID of this layer (read-only)**

        project
- **The project this layer belongs to (read-only)**

        ----------------------------------------------------------------------
        Data descriptors defined here:

        name
            The name of this layer

        state
            The current state of this layer

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

- **__repr__(self)**
- **Return repr(self).**

        ----------------------------------------------------------------------
        Data descriptors inherited from mhi.common.remote.Remotable:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

### class Project(mhi.pscad.remote.Remotable)
- **Project(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        PSCAD Project

        Method resolution order:
            Project
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **__str__(self)**
- **Return str(self).**

- **bookmark(** `@deprecated`
            self,
            name: 'str',
            mouse_x: 'int',
            mouse_y: 'int',
            *callstack: 'Component'
        )
            .. versionremoved:: 3.1.1

- **branch_search(self, subsystem_id: 'int' = 0, node_id: 'int' = 0) -> 'Tuple[Component, ...]'** `@requires` -> `Tuple[Component, ...]`
            Perform a 'Branch Search' in this project

            Project must be compiled for the search to return useful results.

            .. versionadded:: 2.9.6

- **build(self) -> 'None'** -> `None`
            Clean & Build this project, and any dependencies

- **build_modified(self) -> 'None'** -> `None`
            Build this project, and any dependencies

- **button = _component_by_ids(self, defn, *iid)** `@deprecated`

- **canvas(self, name: 'str') -> 'Canvas'** -> `Canvas`
            Retrieve the drawing canvas of a component definition.

            Only T-Lines, Cables, and module-type user components have a canvas.

            Parameters:
- **name (str): Definition name of the component.** `@property` -> `str`

            Returns:
                The corresponding canvas proxy object.

            Getting the main page of a project::

- **main = project.canvas('Main')** -> `Canvas`

            .. versionchanged:: 2.0
- **Was ``Project.user_canvas(name)``** `@deprecated`

- **clean(self) -> 'None'** `@rmi` -> `None`
            Clean the project

- **compile_library(self)** `@requires` `@rmi`
            Compile all resources linked in this library into a single compiled
            ``*.lib`` file.

            .. versionadded:: 2.8

- **component(self, iid: 'int') -> 'Component'** `@rmi` -> `Component`
            Retrieve a component by ID.

            Parameters:
- **iid (int): The ID attribute of the component.**

            .. versionadded:: 2.0
                This command replaces all of the type specific versions.

- **consolidate(self, folder: 'str') -> 'None'** -> `None`
            Moves all files need for this project to the folder, renaming paths
            as needed.

            .. versionadded:: 2.0

- **create_bookmark(** -> `int`
            self,
            name: 'str',
            mouse_x: 'int',
            mouse_y: 'int',
            *callstack: 'Component'
        ) -> 'int'
            Create a bookmark to a particular location of particular instance of
            a component in a call stack.

            .. versionadded:: 3.1.1
- **Renamed from `Project.bookmark(name, mouse_x, mouse_y, callstack)`** `@deprecated`

- **create_definition(self, xml: 'Union[str, ET.Element]') -> 'Definition'** -> `Definition`
            Add a new definition to the project

            Parameters:
- **xml (Union[str, ET.Element]): The definition XML**

            Returns:
                The newly created :class:`.Definition`

- **create_layer(self, name: 'str', state: 'str' = 'Enabled') -> 'Layer'** -> `Layer`
            Create a new layer

            Parameters:
- **name (str): Name of the layer to create.** `@property` -> `str`
- **state (str): Initial state of layer (optional, default='Enabled')**

- **create_resource(self, path: 'str') -> 'Resource'** -> `Resource`
            Add a new resource to the Project's resource folder

            Parameter:
- **path (str): Pathname of the resource**

- **current_canvas(self) -> 'Canvas'** `@requires` -> `Canvas`
            Retrieve the currently focuses canvas of the project.

            Returns:
                The currently focused canvas.

            .. versionadded:: 2.3.2

- **definition(self, name: 'str') -> 'Definition'** -> `Definition`
            Retrieve the given named definition from the project.

            Parameters:
- **name (str): The name of the definition.** `@property` -> `str`

            Returns:
                The named :class:`.Definition`.

            .. versionchanged:: 2.0
- **Was ``ProjectCommands.get_definition()``** `@deprecated`

- **definitions(self) -> 'List[str]'** `@rmi` -> `List[str]`
            Retrieve a list of all definitions contained in the project.

            Returns:
                List[str]: A list of all of the :class:`.Definition` names.

            .. versionchanged:: 2.0
- **Was ``ProjectCommands.list_definitions()``** `@deprecated`

- **delete_definition(self, name: 'str') -> 'None'** -> `None`
            Delete the given named :class:`.Definition`.

            Parameters:
- **name (str): The name of the definition to delete.** `@property` -> `str`

- **delete_definition_instances(self, name: 'str') -> 'None'** -> `None`
            Delete the given named :class:`.Definition`, along with all instances
            of the that definition.

            Parameters:
- **name (str): The name of the :class:`.Definition` whose definition                and instances are to be deleted.** `@property` -> `str`

- **delete_layer(self, name: 'str') -> 'None'** -> `None`
            Delete an existing layer

            Parameters:
- **name (str): Name of the layer to delete.** `@property` -> `str`

- **delete_layers(self, *names: 'str') -> 'None'** -> `None`
            Delete existing layers

            Parameters:
- ***names (str): Name of the layer to delete.**

- **delete_scenario(self, name: 'str') -> 'None'** -> `None`
            Delete the named scenario.

            Parameters:
- **name (str): Name of scenario to delete.** `@property` -> `str`

- **export_parameter_grid(self, filename: 'str', folder: 'Optional[str]' = None) -> 'None'** -> `None`
            Export parameters to a CSV file.

            Parameters:
- **filename (str): Filename of the CSV file to write.** `@rmi_property` -> `str`
- **folder (str): Directory where the CSV file will be stored (optional)**

- **find(self, *names: 'str', layer: 'Optional[str]' = None, **params) -> 'Optional[Component]'** -> `Optional[Component]`
- **find( [[definition,] name,] [layer=name,] [key=value, ...])** -> `Optional[Component]`

- **Find the (singular) component that matches the given criteria,**
            or ``None`` if no matching component can be found.
            Raises an exception if more than one component matches
            the given criteria.

            .. versionadded:: 2.0

- **find_all(self, *name: 'str', layer: 'Optional[str]' = None, **params) -> 'List[Component]'** -> `List[Component]`
- **find_all( [[definition,] name,] [layer=name,] [key=value, ...])** -> `List[Component]`

            Find all components that match the given criteria.

            Parameters:
- **definition (str): One of "Bus", "TLine", "Cable", "GraphFrame",** -> `Definition`
                    "Sticky", or a colon-seperated definition name, such as
- **"master:source3" (optional)**
- **name (str): the component's name, as given by a parameter** `@property` -> `str`
                    called "name", "Name", or "NAME".
                    If no definition was given, and if the provided name is
                    "Bus", "TLine", "Cable", "GraphFrame", "Sticky", or
                    contains a colon, it is treated as the definition name.
- **(optional)**
- **layer (str): only return components on the given layer (optional)** `@rmi` -> `Layer`
                key=value: A keyword list specifying additional parameters
                   which must be matched.  Parameter names and values must match
                   exactly. For example, Voltage="230 [kV]" will not match
                   components with a Voltage parameter value of "230.0 [kV]".
- **(optional)**

            Returns:
                List[ZComponent]: The list of matching components,
                or an empty list if no matching components are found.

            Examples::

- **c = find_all('Bus'                # all Bus components** -> `List[Component]`
- **c = find_all('Bus10')             # all components named "Bus10"** -> `List[Component]`
- **c = find_all('Bus', 'Bus10')      # all Bus component named "Bus10"** -> `List[Component]`
- **c = find_all('Bus', BaseKV='138') # all Buses with BaseKV="138"** -> `List[Component]`
- **c = find_all(BaseKV='138')        # all components with BaseKV="138"** -> `List[Component]`

            .. versionadded:: 2.0

- **find_first(self, *names: 'str', layer: 'Optional[str]' = None, **params) -> 'Optional[Component]'** -> `Optional[Component]`
- **find_first( [[definition,] name,] [layer=name,] [key=value, ...])** -> `Optional[Component]`

            Find the first component that matches the given criteria,
            or ``None`` if no matching component can be found.

            .. versionadded:: 2.0

- **focus(self) -> 'None'** `@rmi` -> `None`
            Switch PSCAD's focus to this project.

- **get_definition(self, name)** `@deprecated`

- **get_output(self)** `@deprecated`

- **get_output_text(self)** `@deprecated`

- **get_run_status(self)** `@deprecated`

        global_substitution = <functools.cached_property object>
            The global substitution container for the project.
            Can be referenced as a dictionary of dictionaries.
            ``Dict[SetName, Dict[VariableName, Value]]``

            Examples::

- **prj.global_substitution.create_sets('Set1', 'Set2')**
- **prj.global_substitution.create('freq', 'VBase')**
                prj.global_substitution['']['freq'] = "60.0 [Hz]"      # Default set
                prj.global_substitution['Set1']['freq'] = "50.0 [Hz]"
                prj.global_substitution['Set2'] = { 'freq': "60.0 [Hz]", 'VBase': '13.8 [kV]' }
                prj.global_substitution.active_set = "Set1"

                # List all global substitution sets
- **>>> list(prj.global_substitution))**
                ['', 'Set1', 'Set2']

                # Print active global substitutions:
                >>> gs = prj.global_substitution
- **>>> for name, value in gs[gs.active_set].items():**
- **print(name, "=", value)**


                freq = 50.0 [Hz]
                VBase =

- **graph_frame = _component_by_id(self, defn, iid)** `@deprecated`

- **import_parameter_grid(self, filename: 'str', folder: 'Optional[str]' = None) -> 'None'** -> `None`
            Import parameters from a CSV file.

            Parameters:
- **filename (str): Filename of the CSV file to read.** `@rmi_property` -> `str`
- **folder (str): Directory to read the CSV file from (optional)**

- **is_dirty(self) -> 'bool'** -> `bool`
            Check if the project contains unsaved changes

            Returns:
                `True`, if unsaved changes exist, `False` otherwise.

- **layer(self, name: 'str') -> 'Layer'** `@rmi` -> `Layer`
            Fetch the given layer

            .. versionadded:: 2.0

- **layer_states(self, name: 'str') -> 'List[str]'** `@rmi` -> `List[str]`
            Fetch all valid states for the given layer

            .. versionadded:: 2.0

- **layers(self) -> 'Dict[str, str]'** `@rmi` -> `Dict[str, str]`
            Fetch the state of all of the layers

            .. versionadded:: 2.0

- **list_definitions(self)** `@deprecated`

- **list_messages(self)** `@deprecated`

- **list_scenarios(self)** `@deprecated`

- **merge_layers(self, dest: 'str', *names: 'str')**
            Merge the list of layers into a layer with the name provided.

            Parameters:
- **dest (str): The name of the layer to merge to, created if necessary**
- ***names (str): Layers to merge into the destination layer**

            Returns:
                Layer: The destination layer

- **messages(self) -> 'List[Message]'** -> `List[Message]`
            Retrieve the load/build messages

            Returns:
                List[Message]: A list of messages associated with the project.

            Each message is a named tuple composed of:

            ====== ====================================================
            text   The message text
            label  Kind of message, such as build or load
            status Type of messages, such as normal, warning, or error.
            scope  Project to which the message applies
            name   Component which caused the message
            link   Id of the component which caused the message
            group  Group id of the message
            ====== ====================================================

            Example::

- **pscad.load('tutorial/vdiv.pscx', folder=pscad.examples_folder)**
- **vdiv = pscad.project('vdiv')**
- **vdiv.build()** -> `None`
- **for msg in vdiv.messages():** -> `List[Message]`
- **print(msg.text)**

- **move_layers_down(self, *names: 'str', delta: 'int' = 1)**
            Move the list of layers down the list by 1

- **move_layers_up(self, *names: 'str', delta: 'int' = 1)**
            Move the list of layers up the list by 1

- **names_in_use(self, defn: 'Optional[str]' = None, **params) -> 'Set[str]'** -> `Set[str]`
            Return the set of "Name" parameter values, for all components on the
            canvas that have a "Name" parameter.

- **navigate_to(self, *components: 'Component')**
            Navigate to a particular instance of component in a call stack

- **node_search(** `@requires` -> `Tuple[Component, ...]`
            self,
            subsystem_id: 'int',
            node_id: 'int',
            look_in: 'LookIn',
            global_flag: 'bool'
        ) -> 'Tuple[Component, ...]'
            Perform a 'Node Search' with this project

            Project must be compiled for the search to return useful results.

            .. versionadded:: 2.9.6

- **output(self) -> 'str'** `@rmi` -> `str`
- **Retrieve the output (run messages) for the project** `@rmi` -> `str`

            Returns:
                str: The output messages

            Example::

- **pscad.load('tutorial/vdiv.pscx', folder=pscad.examples_folder)**
- **vdiv = pscad.project('vdiv')**
- **vdiv.run()** -> `None`
- **print(vdiv.output())**

            .. versionchanged:: 2.0
- **Was ``ProjectCommands.get_output_text()``** `@deprecated`

- **overlay_graph = _component_by_ids(self, defn, *iid)** `@deprecated`

- **parameter_range(self, parameter: 'str') -> 'ParameterRange'** -> `ParameterRange`
            Get legal values for a parameter

            Example::

- **>>> vdiv.parameter_range('SnapType')** -> `ParameterRange`
- **frozenset({'ONLY_ONCE', 'NONE', 'INCREMENTAL_SAME_FILE', 'INCREMENTAL_MANY_FILES'})**

            .. versionadded:: 2.0

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Get or set project parameters

            Parameters:
- **parameters (dict): A dictionary of name=value parameters** -> `Optional[Parameters]`
                **kwargs: Zero or more name=value keyword parameters

            Returns:
                A dictionary of current parameters, if no parameters were given.


            .. table:: Project Parameters

                ================= ====== ===========================================
                Param Name        Type   Description
                ================= ====== ===========================================
                description       str    Description
                time_step         float  Solution time step
                time_duration     float  Duration of run
                sample_step       float  Channel plot step
                PlotType          choice Save to: `"NONE"`, `"OUT"`, `"PSOUT"`
                output_filename   str    Name of data file, with .out extension
                StartType         int    Start simulation: 0=Standard,                                     1=From Snapshot File
                startup_filename  str    Start up snapshot file name
- **SnapType          int    Timed Snapshot: 0=None, 1=Single,                                     2=Incremental (same file),                                     3=Incremental (multiple file)**
                SnapTime          float  Snapshot time as a real number
                snapshot_filename str    Save snapshot as text
                MrunType          int    Run config 0=Standalone, 1=Master, 2=Slave
                Mruns             int    Number of multiple runs
                ================= ====== ===========================================

- **paste_definitions(self) -> 'None'** `@requires` -> `None`
            Paste definitions from the clipboard into this project.

            .. versionadded:: 2.9

- **paste_definitions_with_dependents(self) -> 'None'** `@requires` -> `None`
            Paste definitions and their dependents from the clipboard
            into this project.

            .. versionadded:: 2.9

- **pause(self) -> 'None'** -> `None`
            Pause the currently running projects.

            Note:
                All projects being run will be paused, not just this project.

- **reload(self) -> 'None'** -> `None`
            Reload this project.

            The project is unloaded, without saving any unsaved modifications,
            and then immediately reloaded.
            This returns the project to the state it was in when it was last
            saved.

            .. versionadded:: 2.0

- **remap_definitions(self, old: 'Project', new: 'Project', *definitions: 'str') -> 'None'** `@requires` -> `None`
            Remap definitions from one namespace to another namespace.

            .. versionadded:: 3.0.2

- **remove_resource(self, resource: 'Resource')** `@rmi`
            Remove a resource

- **resource(self, path: 'str') -> 'Resource'** `@rmi` -> `Resource`
            Find a resource by path

- **resources(self) -> 'List[Resource]'** `@rmi` -> `List[Resource]`
            Fetch list of all resources in project

- **run(self, consumer=None) -> 'None'** -> `None`
            Build and run this project.

            Parameters:
- **consumer: handler for events generated by the build/run (optional).** -> `None`

            Note:
                A library cannot be run; only a case can be run.

- **run_status(self) -> 'Tuple[Optional[str], Optional[int]]'** `@rmi` -> `Tuple[Optional[str], Optional[int]]`
            Get the run status of the project

            Returns:
- **Returns `("Build", None)` if building, `("Run", percent)` if running,**
- **or `(None, None)` otherwise.**

            .. versionchanged:: 2.0
- **Was ``ProjectCommands.get_run_status()``** `@deprecated`

- **save(self) -> 'None'** -> `None`
            Save changes made to this project

- **save_as(** -> `Project`
            self,
            filename: 'Union[str, PureWindowsPath]',
            ver46: 'bool' = False,
            folder: 'Optional[Union[str, PureWindowsPath]]' = None
        ) -> 'Project'
            Save this project under a new name.

            The project will be saved using the appropriate extension depending
- **on whether the project is a case (``.pscx``) or library (``.pslx``).**

            The filename must conform to PSCAD naming convensions:

            * it must start with a letter,
            * remaining characters must be alphanumeric or the underscore ``_``,
            * cannot exceed 30 characters.

            Parameters:
- **filename (str): The name or filename to store project to.** `@rmi_property` -> `str`
- **ver46 (bool): Set to true to store as a version 4.6 file. (optional)**
- **folder (str): If provided, the path to the filename is resolved**
- **relative to this folder. (optional)**

            Notes:
                When the project name is changed, all existing Python handles to
                the project and anything within it become invalid and must not be
                used.

            .. versionchanged:: 2.0
                Added ``ver46`` parameter.
            .. versionchanged:: 2.7.2
                Added ``folder`` parameter; returns the new project object.

- **save_as_scenario(self, name: 'str') -> 'None'** -> `None`
            Save the current configuration under the given scenario name.

            Parameters:
- **name (str): Name of scenario to create or overwrite.** `@property` -> `str`

- **save_scenario(self) -> 'None'** -> `None`
            Save the current scenario.

            .. versionadded:: 2.0

- **scenario(self, name: 'Optional[str]' = None) -> 'str'** `@rmi` -> `str`
            Get or set the current scenario.

            Parameters:
- **name (str): Name of scenario to switch to (optional).** `@property` -> `str`

            Returns:
- **str: The name of the (now) current scenario.**

- **scenarios(self) -> 'List[str]'** `@rmi` -> `List[str]`
            List the scenarios which exist in the project.

            Returns:
                List[str]: List of scenario names.

            .. versionchanged:: 2.0
- **Was ``ProjectCommands.list_scenarios()``** `@deprecated`

- **selector = _component_by_ids(self, defn, *iid)** `@deprecated`

- **set_layer(self, name, state)** `@deprecated`
            Set the state of a layer

            Parameters:
- **name (str): Name of the layer to alter.** `@property` -> `str`
- **state (str): "Enabled", "Disabled", "Invisible" or a custom state.**

- **set_layer_state(self, name: 'str', state: 'str') -> 'None'** -> `None`
            Set the state of a layer

            Parameters:
- **name (str): Name of the layer to alter.** `@property` -> `str`
- **state (str): "Enabled", "Disabled", "Invisible" or a custom state.**

            .. versionchanged:: 2.0
- **Renamed from ``.set_layer(state)``** `@deprecated`

- **set_parameters(self, parameters=None, **kwargs)** `@deprecated`

- **slider = _component_by_ids(self, defn, *iid)** `@deprecated`

- **start(self) -> 'None'** -> `None`
            Start the current project running.

            Note:
                Returns immediately.

- **stop(self) -> 'None'** `@rmi` -> `None`
            Terminate a running execution of this project.

- **switch = _component_by_ids(self, defn, *iid)** `@deprecated`

- **unload(self) -> 'None'** -> `None`
            Unload this project.

            The project is unloaded.
            All unsaved changes are lost.

            .. versionadded:: 2.0

- **user_canvas(self, name)** `@deprecated`

- **user_cmp = _component_by_id(self, defn, iid)** `@deprecated`

        ----------------------------------------------------------------------
        Static methods defined here:

- **validate_name(name) -> 'None'** `@staticmethod` -> `None`
            The ``name`` must conform to PSCAD naming convensions:

            * it must start with a letter,
            * remaining characters must be alphanumeric or the underscore ``_``,
            * cannot exceed 30 characters.

            Raises a ``ValueError`` is an invalid name is given.

        ----------------------------------------------------------------------
        Readonly properties defined here:

        dirty
- **Has the project been modified since it was last saved (read-only)**

            .. versionadded:: 2.0

        filename
- **The project's file name (read-only)** `@property` -> `str`

            .. versionadded:: 2.0

        name
- **The name of the project (read-only)**

            .. versionadded:: 2.0

        temp_folder
- **The project's compiler-dependent temporary folder (read-only).**

            .. versionadded:: 2.1

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {'_canvas_cache': 'LingeringCache[str, Canvas]', '_d...

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

### class Resource(mhi.pscad.remote.Remotable)
- **Resource(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Project Resource

        Method resolution order:
            Resource
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__repr__(self) -> 'str'** -> `str`
- **Return repr(self).**

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Get/Set Resource parameters

        ----------------------------------------------------------------------
        Readonly properties defined here:

        abspath
            The absolute path of the this resource.

        id
- **The ID of this resource (read-only)**

        name
            The name of the this resource.

        path
            The path of the this resource, relative to the project.

        project
- **The project this resource belongs to (read-only)**

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
    DefaultDict = typing.DefaultDict
        A generic version of collections.defaultdict.

    Dict = typing.Dict
        A generic version of dict.

    LOG = <Logger mhi.pscad.project (INFO)>
    List = typing.List
        A generic version of list.

    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    ParameterRange = typing.Union[typing.Tuple, typing.Set, range, NoneTyp...
    Parameters = typing.Dict[str, typing.Any]
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
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/project.py
