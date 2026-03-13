# Module mhi.pscad.simset

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/simset.py*

Python Library Documentation: module mhi.pscad.simset in mhi.pscad

## NAME
    mhi.pscad.simset

## DESCRIPTION
    **************
    Simulation Set
    **************

    .. autoclass:: SimulationSet


    Management
    ----------

    .. automethod:: SimulationSet.name


    Tasks
    -----

    .. automethod:: SimulationSet.list_tasks
    .. automethod:: SimulationSet.add_tasks
    .. automethod:: SimulationSet.remove_tasks
    .. automethod:: SimulationSet.task


    Build & Run
    -----------

    .. automethod:: SimulationSet.run

## CLASSES
    mhi.pscad.remote.Remotable(mhi.common.remote.Remotable)
        SimsetTask
            ExternalTask
            ProjectTask
        SimulationSet

### class ExternalTask(SimsetTask)
- **ExternalTask(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        External Simulation Set Task

        Method resolution order:
            ExternalTask
            SimsetTask
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
- **parameters(parameter=value, ...)** -> `Optional[Parameters]`
            Get/set External Task Settings

            .. table:: External Task Settings

               ============= ====== ===========================================
               Param Name    Type   Description
               ============= ====== ===========================================
               name          Text   Name
               path          Path   Process to Launch
               args          Text   Arguments
               platform      Choice Platform: X86, X64
               ============= ====== ===========================================

- **stop(self) -> 'None'** `@rmi` -> `None`
            Unconditionally stop the external task

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from SimsetTask:

- **__str__(self)**
- **Return str(self).**

- **move_down(self) -> 'None'**
            Move the task down one spot in the the task list of the simulation

- **move_up(self) -> 'None'**
            Move the task up one spot in the the task list of the simulation

- **to_bottom(self) -> 'None'**
            Move the task to the bottom of the task list of the simulation

- **to_top(self) -> 'None'**
            Move the task to the top of the task list of the simulation

        ----------------------------------------------------------------------
        Readonly properties inherited from SimsetTask:

        name
            Name of this project task

        simulation_set
            Simulation set the task is part of

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

### class ProjectTask(SimsetTask)
- **ProjectTask(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Project Simulation Set Task

        Method resolution order:
            ProjectTask
            SimsetTask
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__getitem__(self, key)**

- **__repr__(self)**
- **Return repr(self).**

- **affinity(self, affinity=None)** `@deprecated`
            Get or set the affinity

- **controlgroup(self, controlgroup=None)** `@deprecated`

- **layers(** -> `Dict[str, Union[str, bool, None]]`
            self,
            layer_states: 'Optional[Dict[str, Union[str, bool, None]]]' = None,
            **kwargs
        ) -> 'Dict[str, Union[str, bool, None]]'
- **layers(layer_name=state, ...)** -> `Dict[str, Union[str, bool, None]]`
            Get / set layer overrides for this Simulation Task.

            Each layer can be forced into state different from the project's
            default state.

            .. table:: Layer State Overrides

               ============ ========================================================
               State        Description
               ============ ========================================================
               ``None``     Inherit from the project's layer state
               ``True``     Force the layer to be enabled
               ``False``    Force the layer to be disabled
               ``"Custom"`` Force the layer into the configuration named "Custom"
               ============ ========================================================

            Returns:
                dict: The current simulation task's layer overrides.

            Example::

                # When this simulation set task runs, force the "region1" layer
                # to be enabled, the "region2" layer to be disabled, and the
                # "region3" layer into a custom layer configuration.  Remove any
                # override that was previously applied to "region4" in this task.

- **task.layers(region1=True, region2=False, region3="Special",** -> `Dict[str, Union[str, bool, None]]`
                            region4=None)

- **namespace(self) -> 'str'** -> `str`
            Get the namespace of the task

- **overrides(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
- **overrides(parameter=value, ...)** -> `Optional[Parameters]`
            Get / set override parameters for this Simulation Task.

            .. table:: Project Task Override Parameters

                ======================= ===== =============================================
                Parameter Name          Type  Description
                ======================= ===== =============================================
- **duration                float Duration of run (sec)**
- **time_step               float Simulation time-step (µs)**
                plot_step               float Output channel plot step
                start_method            int   Startup Method.  0=Standard, 1=From Snapshot
                startup_inputfile       str   Input filename
                save_channels_file      str   Output filename
- **save_channels           int   0=Do not save, 1=Legacy Format (``*.out``),                                             2=Advanced Format (``*.psout``)**
- **timed_snapshots         int   0=None, 1=Single, 2=Incremental (Same File),                                             3=Incremental (Many Files)**
                snapshot_file           str   Snapshot filename
                snap_time               float Snapshot time
                run_config              int   0=Standalone, 1=Master, 2=Slave
                run_count               int   Number of runs
                remove_snapshot_offset  bool  Remove snapshot time offset
                only_in_use_channels    bool  Only send "in use" channels
                state_animation         bool  Enable animation
                manual_start            bool  Manual Start
                ======================= ===== =============================================

            For each of the above parameters, there is an additional parameter,
            prefixed with ``override_``, which controls whether this parameter is used.
            It is automatically set to ``"true"`` if a value other than ``None`` is given,
            and to ``"false"`` if the `None` value is given.

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
- **parameters(parameter=value, ...)** -> `Optional[Parameters]`
            Get/set simulation set task parameters

            .. table:: Project Task Parameters

               ============= ===== ============================================
               Param Name    Type  Description
               ============= ===== ============================================
- **namespace     str   Namespace of project (read-only)**
               name          str   Display Name
               ammunition    int   Task count
               volley        int   Maximum Volley
               affinity      int   Trace Affinity
               rank_snap     bool  Specify snapshot file by rank #?
               substitutions str   Substitution set
               clean         bool  Force Re-Build
               ============= ===== ============================================

- **volley(self, volley=None)** `@deprecated`
            Get or set the volley count

        ----------------------------------------------------------------------
        Data and other attributes defined here:

        __annotations__ = {}

        ----------------------------------------------------------------------
        Methods inherited from SimsetTask:

- **__str__(self)**
- **Return str(self).**

- **move_down(self) -> 'None'**
            Move the task down one spot in the the task list of the simulation

- **move_up(self) -> 'None'**
            Move the task up one spot in the the task list of the simulation

- **to_bottom(self) -> 'None'**
            Move the task to the bottom of the task list of the simulation

- **to_top(self) -> 'None'**
            Move the task to the top of the task list of the simulation

        ----------------------------------------------------------------------
        Readonly properties inherited from SimsetTask:

        name
            Name of this project task

        simulation_set
            Simulation set the task is part of

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

### class SimsetTask(mhi.pscad.remote.Remotable)
- **SimsetTask(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

- **Simulation Set Task (Abstract)**

        Method resolution order:
            SimsetTask
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__str__(self)**
- **Return str(self).**

- **move_down(self) -> 'None'** -> `None`
            Move the task down one spot in the the task list of the simulation

- **move_up(self) -> 'None'** -> `None`
            Move the task up one spot in the the task list of the simulation

- **to_bottom(self) -> 'None'** -> `None`
            Move the task to the bottom of the task list of the simulation

- **to_top(self) -> 'None'** -> `None`
            Move the task to the top of the task list of the simulation

        ----------------------------------------------------------------------
        Readonly properties defined here:

        name
            Name of this project task

        simulation_set
            Simulation set the task is part of

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

### class SimulationSet(mhi.pscad.remote.Remotable)
- **SimulationSet(**
            *,
            _ctx: 'Optional[Context]' = None,
            _ident: 'Optional[Dict[str, Any]]' = None
        )

        Simulation Set

        A container of Project and External Simulation Set Tasks

        Method resolution order:
            SimulationSet
            mhi.pscad.remote.Remotable
            mhi.common.remote.Remotable
            builtins.object

        Methods defined here:

- **__repr__(self)**
- **Return repr(self).**

- **add_external_task(self, filename: 'str', folder: 'Optional[str]' = None) -> 'ExternalTask'** -> `ExternalTask`
- **Add an external task (executable) to the simulation set.** `@rmi` -> `ProjectTask`

            Parameters:
- **filename (str): The executable's filename**
- **folder (str): Folder of the executable (optional)**

            Returns:
                ExternalTask: The external task

- **add_task(self, task: 'Union[str, Project]') -> 'ProjectTask'** `@rmi` -> `ProjectTask`
            Add a project task to the simulation set.

            Parameters:
                task: The project to add as a project task to the simulation set.

            Returns:
                ProjectTask: The project task

- **add_tasks(self, *tasks: 'Union[str, Project]') -> 'None'** `@rmi` -> `None`
- **Add one or more tasks (projects) to the simulation set.** `@rmi` -> `List[ProjectTask]`

            Parameters:
- ***tasks: The tasks (projects) to add to the simulation set.** `@rmi` -> `List[ProjectTask]`

- **build(self) -> 'None'** -> `None`
            Build all projects in the simulation set

- **build_modified(self) -> 'None'** -> `None`
            Build any modified projects in the simulation set

- **clean(self) -> 'None'** -> `None`
            Remove temporary files created during build/run

- **clone(self)** `@rmi`
            Duplicate this simulation set

- **depends_on(self, name=None)** `@deprecated`

- **list_tasks(self) -> 'List[str]'** -> `List[str]`
            List task names included in the simulation set.

            Returns:
                List[str]: The names of the tasks in the simulation set.

- **move_down(self) -> 'None'** -> `None`
            Move Simulation Set to up down position in list

- **move_up(self) -> 'None'** -> `None`
            Move Simulation Set to up one position in list

- **name(self, new_name: 'Optional[str]' = None) -> 'str'** -> `str`
            Get or set the simulation set name.

            Parameters:
- **new_name (str): New name for the simulation set (optional)**

            Returns:
                The name of the simulation set

- **parameters(self, parameters: 'Optional[Parameters]' = None, **kwargs) -> 'Optional[Parameters]'** -> `Optional[Parameters]`
            Get/Set simulation set parameters

- **remove_tasks(self, *tasks: 'Union[str, Project, ProjectTask, ExternalTask]') -> 'None'** `@rmi` -> `None`
- **Remove one or more tasks (projects) from the simulation set.** `@rmi` -> `List[ProjectTask]`

            Parameters:
- ***tasks: The tasks (projects) to remove from the simulation set.** `@rmi` -> `List[ProjectTask]`

- **run(self, consumer=None) -> 'None'** -> `None`
            Run this simulation set.

            Parameters:
- **consumer: handler for events generated by the build/run (optional).** -> `None`

- **task(self, name: 'str') -> 'ProjectTask'** `@rmi` -> `ProjectTask`
            Retrieve an individual task in the simulation set.

            Parameters:
- **name (str): Name of task** -> `str`

            Returns:
                ProjectTask: The identified task

- **tasks(self) -> 'List[ProjectTask]'** `@rmi` -> `List[ProjectTask]`
            List projects included in the simulation set.

            Returns:
                List[ProjectTask]: The tasks included in the simulation set.

- **to_bottom(self) -> 'None'** -> `None`
            Move Simulation Set to end of list

- **to_top(self) -> 'None'** -> `None`
            Move Simulation Set to start of list

        ----------------------------------------------------------------------
        Static methods defined here:

- **validate_name(name: 'str')** `@staticmethod`
            The ``name`` must conform to PSCAD naming convensions:

            * should start with a letter,
            * remaining characters must be alphanumeric or the underscore ``_``,
            * cannot exceed 30 characters.

            Raises a ``ValueError`` is an invalid name is given.

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
    Dict = typing.Dict
        A generic version of dict.

    LOG = <Logger mhi.pscad.simset (INFO)>
    List = typing.List
        A generic version of list.

    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

    Parameters = typing.Dict[str, typing.Any]
    TYPE_CHECKING = False
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
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/simset.py
