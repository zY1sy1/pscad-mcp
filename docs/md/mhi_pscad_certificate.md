# Module mhi.pscad.certificate

*Source: /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/certificate.py*

Python Library Documentation: module mhi.pscad.certificate in mhi.pscad

## NAME
    mhi.pscad.certificate

## DESCRIPTION
    ********************
    License Certificates
    ********************

    .. autoclass:: Certificate()


    Identification
    --------------

    .. automethod:: Certificate.id
    .. automethod:: Certificate.name
    .. automethod:: Certificate.account
    .. automethod:: Certificate.available
    .. automethod:: Certificate.total


    Features
    --------

    .. automethod:: Certificate.features
    .. automethod:: Certificate.feature


    Requirements
    ------------

    .. automethod:: Certificate.meets
    .. automethod:: Certificate.meet
    .. automethod:: Certificate.cost

    ****************
    License Features
    ****************

    .. autoclass:: Feature()

    Identification
    --------------

    .. automethod:: Feature.id
    .. automethod:: Feature.name
    .. automethod:: Feature.value
    .. automethod:: Feature.cost

## CLASSES
    builtins.object
        Certificate
        Feature

### class Certificate(builtins.object)
- **Certificate(row_id, node, features)**

        PSCAD License Certificate

        Methods defined here:

- **__getitem__(self, key)**
            If key is a string or an integer, returns the corresponding feature.
- **If the key is a (feature_name_or_id, lower_limit) tuple, the feature's**
            value is retrieved and tested against the specified lower_limit.

- **__init__(self, row_id, node, features)**
            Parses the following XML Node:

            <LicenseGroups>
                <RowID>1971405233</RowID>
                <AccountID>13198</AccountID>
                <AccountName>Beta Account</AccountName>
                <FeatureSetID>2</FeatureSetID>
                <ProductID>13</ProductID>
                <ProductName>PSCAD 4.6.0 RC PRO</ProductName>
                <Count>1</Count>
                <Owned>2</Owned>
                <Notes />
            </LicenseGroups>

            .. versionchanged:: 3.1.1
                Allow for text attributes instead of text child nodes

- **__repr__(self)**
- **Return repr(self).**

- **__str__(self)**
- **Return str(self).**

- **account(self) -> 'str'** -> `str`
            Returns the 'Account Name' for the Certificate

- **available(self) -> 'int'** -> `int`
            Returns the # of available Certificates

- **cost(self) -> 'float'** -> `float`
            The certificate cost may be used by the license selection logic to
            determine which license to acquire from the set of all licenses which
            meet the list of requested features.  The 'cheapest' license would be
            choosen.

            This function returns a cost using a default heuristic.  The method may
            be overridden by setting the class member `Certificate.COST`.

- **feature(self, key: 'Union[str, int]') -> 'Optional[Feature]'** -> `Optional[Feature]`
            Returns a `Feature` associated with the Certificate.  The feature may
- **be specified by name (such as "Freq Dep Network Equivalent") or by** -> `str`
- **an integer id (such as 17).** -> `int`

- **features(self) -> 'List[Feature]'** -> `List[Feature]`
            Returns the list of all features associated with the Certificate.
            Note: This even includes Features where no instances of that feature
            are owned.

- **id(self) -> 'int'** -> `int`
            Returns the ID of the Certificate

- **meet(** -> `bool`
            self,
            key: 'Union[str, int]',
            req: 'Union[str, int, bool, Tuple[int, int]]'
        ) -> 'bool'
            Tests if the certificate meets the given requirement.

            Parameters:
                key: a feature name or the corresponding integer value
                req: one of:

                    - a string: exact match of feature value
                    - a boolean: exact match of feature value
                    - an int: exact match of feature value
                    - a tuple: range of values [low,high] that can match the feature

            Example::

                # Does `cert` disallow black boxing?
- **cert.meet("Blackboxing", False)** -> `bool`

- **meets(self, requirements: 'List[Union[str, int, Tuple[Union[str, int], int]]]') -> 'bool'** -> `bool`
            Tests if the certificate meets the given list of requirements.

            Parameters:
                requirements: A list of requirements.  Each requirement may be                 given as:

                    - a string or integer, in which case the certificate must
                      own the corresponding feature,
- **- a (feature_name_or_id, lower_limit) tuple, in which case**
                      the feature must have a value greater than or equal to the limit.

            Example::

                # Does `cert` allow black boxing and 20 or more EMTDC instances?
- **cert.meets(["Blackboxing", ("EMTDC Instances", 20)])** -> `bool`

- **name(self) -> 'str'** -> `str`
            Returns the 'Product Name' for the Certificate

- **total(self) -> 'int'** -> `int`
            Returns the total # of Certificates

        ----------------------------------------------------------------------
        Static methods defined here:

- **COST = _default_cost(certificate) -> 'float'** `@staticmethod` -> `float`
            The cost of a certificate is calculated as the sum of the cost of the
- **individual features, plus an additional premium for 'rare' (small values**
- **for cert.total()) certificates.** -> `int`

            The certificate cost is used by the license selection logic to determine
            which license to acquire from the set of all licenses which meet the
            list of requested features.  The 'cheapest' license is choosen.

            This function may be overridden to alter the certificate cost, altering
            the license selection logic.

- **find_cert(certs, xml)** `@staticmethod`
            Locate a certificate from an XML description

- **parse(msg)** `@staticmethod`
            Parses a <NewDataSet> XML node containing a list of <LicenseGroups/>
            and <Features/> nodes, and returns a dictionary containing all of the
- **LicenseGroups, keyed by the Certificate.id()** -> `int`

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

### class Feature(builtins.object)
- **Feature(node)**

        A feature of a license :class:`.Certificate`.

        Methods defined here:

- **__bool__(self)**
            Is this feature 'owned'

- **__eq__(self, val)**
            Return self==value.

- **__ge__(self, val)**
            Does this feature have a 'value' greater than or equal to ...

- **__gt__(self, val)**
            Does this feature have a 'value' greater than ...

- **__init__(self, node)**
            Parses the following XML nodes:

            <Features>
                <RowID>1444555977</RowID>
                <FeatureID>12</FeatureID>
                <FeatureName>EMTDC Instances</FeatureName>
                <Owned>1</Owned>
                <FeatureValue>16</FeatureValue>
                <Notes />
            </Features>

            .. versionchanged:: 3.1.1
                Allow for text attributes instead of text child nodes

- **__le__(self, val)**
            Does this feature have a 'value' less than or equal to ...

- **__lt__(self, val)**
            Does this feature have a 'value' less than ...

- **__repr__(self)**
- **Return repr(self).**

- **__str__(self)**
- **Return str(self).**

- **cost(self) -> 'float'** -> `float`
            Computes the 'cost' of a feature.

            `Feature.COSTS` is a dictionary, indexed by feature name, of tuples
            containing the fixed and variable cost for a feature::

- **fixed, variable = COSTS[feature.name()]** -> `str`
- **cost = fixed + variable * feature.value()** -> `Optional[int]`

            The certificate cost is used by the license selection logic to determine
            which license to acquire from the set of all licenses which meet the
            list of requested features.  The 'cheapest' license is choosen.

            The fixed and variable costs specified here are arbitrary, and may be
            changed to alter the license selection.

- **id(self) -> 'int'** -> `int`
            Returns the Feature's ID.

- **name(self) -> 'str'** -> `str`
            Returns the Feature's name.

- **value(self) -> 'Optional[int]'** -> `Optional[int]`
            Returns the Feature's value.

        ----------------------------------------------------------------------
        Data descriptors defined here:

        __dict__
            dictionary for instance variables

        __weakref__
            list of weak references to the object

        ----------------------------------------------------------------------
        Data and other attributes defined here:

- **COSTS = {'Blackboxing': (7, 0), 'EMTDC Instances': (0, 0.1), 'Electric...**

- **DEFAULT_COST = (0, 0)**

        __hash__ = None

## DATA
    List = typing.List
        A generic version of list.

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
    /home/lua/miniconda/lib/python3.13/site-packages/mhi/pscad/certificate.py
