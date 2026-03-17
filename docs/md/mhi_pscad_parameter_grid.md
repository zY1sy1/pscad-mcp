# Module mhi.pscad.parameter_grid

*Source: C:\Users\AS0135\AppData\Local\Programs\Python\Python314\Lib\site-packages\mhi\pscad\parameter_grid.py*

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

- **view(self, subject: Union[Component, Definition, Project]) -> None** -> `None`
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

- **view_simulation_task_layers(self, scope: Union[Project, str]) -> None** -> `None`
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

## FILE
    c:\users\as0135\appdata\local\programs\python\python314\lib\site-packages\mhi\pscad\parameter_grid.py
