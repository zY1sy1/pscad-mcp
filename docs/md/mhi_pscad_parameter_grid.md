# Module mhi.pscad.parameter_grid

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/parameter_grid.py*

Python Library Documentation: module mhi.pscad.parameter_grid in mhi.pscad

## NAME
    mhi.pscad.parameter_grid - The PSCAD Parameter Grid Proxy Object

## CLASSES
    builtins.object
        ParameterGrid

### class ParameterGrid(builtins.object)
- **ParameterGrid(pscad)**

        The Parameter Grid interface

        Methods defined here:

- **__init__(self, pscad)**
- **Initialize self.  See help(type(self)) for accurate signature.**

- **load(self, filename: str, folder: Optional[str] = None) -> None** -> `None`
            Load parameter grid from a CSV file.

            Parameters:
- **filename (str): Filename of the CSV file to read.**
- **folder (str): Directory to read the CSV file from (optional)**

- **save(self, filename: str, folder: Optional[str] = None) -> None** -> `None`
            Write parameter grid to a CSV file.

            Parameters:
- **filename (str): Filename of the CSV file to write.**
- **folder (str): Directory where the CSV file will be stored (optional)**

- **view(** -> `None`
            self,
            subject: Union[mhi.pscad.component.Component, mhi.pscad.definition.Definition, mhi.pscad.project.Project]
        ) -> None
            Load subject into the parameter grid.

            The property grid is able to view and modify several components at
            once.

            If the subject is a component or component definition, all of the
            instances of that component are loaded into the parameter grid.

            If the subject is a project, all of the corresponding project types
- **(libraries or cases) are loaded into the parameter grid.**

- **view_cases(self) -> None** `@requires` -> `None`
            Load all project cases into the parameter grid.

- **view_libraries(self) -> None** `@requires` -> `None`
            Load all libraries into the parameter grid.

            Note: The 'master' library is always omitted.

- **view_simulation_sets(self) -> None** -> `None`
            Load all simulation sets into the property grid.

            This allows for viewing / editing multiple simulation sets in the
            workspace at once.

- **view_simulation_task_layers(self, scope: Union[mhi.pscad.project.Project, str]) -> None** -> `None`
            Load simulation tasks' layers configurations into the property grid.

            This allows for viewing / editing multiple sets of layers
            configurations in the workspace at once.

            Parameters:
                scope: The project object or a project name

- **view_simulation_task_overrides(self) -> None** -> `None`
            Load simulation tasks' project overrides into the property grid.

            This allows for viewing / editing multiple sets of project overrides
            in the workspace at once.

- **view_simulation_tasks(self) -> None** -> `None`
            Load all simulation tasks into the property grid.

            This allows for viewing / editing multiple simulation tasks in the
            workspace at once.

        ----------------------------------------------------------------------
        Readonly properties defined here:

        main
            Main PSCAD application reference

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

## DATA
    LOG = <Logger mhi.pscad.parameter_grid (INFO)>
    Optional = typing.Optional
        Optional[X] is equivalent to Union[X, None].

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
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/parameter_grid.py
