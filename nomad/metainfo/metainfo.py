# Copyright 2018 Markus Scheidgen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an"AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
The NOMAD meta-info allows to define physics data quantities. These definitions are
necessary for all computer representations of respective data (e.g. in Python,
search engines, data-bases, and files).

This modules provides various Python interfaces for

- defining meta-info data
- to create and manipulate data that follows these definitions
- to (de-)serialize meta-info data in JSON (i.e. represent data in JSON formatted files)

Here is a simple example that demonstrates the definition of System related quantities:

.. code-block:: python

    class System(MSection):
        \"\"\"
        A system section includes all quantities that describe a single a simulated
        system (a.k.a. geometry).
        \"\"\"

        n_atoms = Quantity(
            type=int, description='''
            A Defines the number of atoms in the system.
            ''')

        atom_labels = Quantity(type=Enum(ase.data.chemical_symbols), shape['n_atoms'])
        atom_positions = Quantity(type=float, shape=['n_atoms', 3], unit=Units.m)
        simulation_cell = Quantity(type=float, shape=[3, 3], unit=Units.m)
        pbc = Quantity(type=bool, shape=[3])

    class Run(MSection):
        systems = SubSection(sub_section=System, repeats=True)

Here, we define a `section` called ``System``. The section mechanism allows to organize
related data into, well, sections. Sections form containment hierarchies. Here
containment is a parent-child (whole-part) relationship. In this example many ``Systems``,
are part of one ``Run``. Each ``System`` can contain values for the defined quantities:
``n_atoms``, ``atom_labels``, ``atom_positions``, ``simulation_cell``, and ``pbc``.
Quantities allow to state type, shape, and physics unit to specify possible quantity
values.

Here is an example, were we use the above definition to create, read, and manipulate
data that follows these definitions:

.. code-bock:: python

    run = Run()
    system = run.m_create(System)
    system.n_atoms = 3
    system.atom_labels = ['H', 'H', 'O']

    print(system.atom_labels)
    print(run.m_to_json(ident=2))

This last statement, will produce the following JSON:

.. code-block:: JSON

    {
        "m_def" = "Run",
        "System": [
            {
                "m_def" = "System",
                "m_parent_index" = 0,
                "n_atoms" = 3,
                "atom_labels" = [
                    "H",
                    "H",
                    "O"
                ]
            }
        ]
    }

This is the JSON representation, a serialized version of the Python representation in
the example above.

Sections can be extended with new quantities outside the original section definition.
This provides the key mechanism to extend commonly defined parts with (code) specific
quantities:

.. code-block:: Python

    class Method(nomad.metainfo.common.Method):
        x_vasp_incar_ALGO=Quantity(
            type=Enum(['Normal', 'VeryFast', ...]),
            links=['https://cms.mpi.univie.ac.at/wiki/index.php/ALGO'])
        \"\"\"
        A convenient option to specify the electronic minimisation algorithm (as of VASP.4.5)
        and/or to select the type of GW calculations.
        \"\"\"


All meta-info definitions and classes for meta-info data objects (i.e. section instances)
inherit from :class:` MSection`. This base-class provides common functions and properties
for all meta-info data objects. Names of these common parts are prefixed with ``m_``
to distinguish them from user defined quantities. This also constitute's the `reflection`
interface (in addition to Python's build in ``getattr``, ``setattr``) that allows to
create and manipulate meta-info data, without prior program time knowledge of the underlying
definitions.

.. autoclass:: MSection

The following classes can be used to define and structure meta-info data:

- sections are defined by sub-classes :class:`MSection` and using :class:`Section` to
  populate the classattribute `m_def`
- quantities are defined by assigning classattributes of a section with :class:`Quantity`
  instances
- references (from one section to another) can be defined with quantities that use
  section definitions as type
- dimensions can use defined by simply using quantity names in shapes
- categories (former `abstract type definitions`) can be given in quantity definitions
  to assign quantities to additional specialization-generalization hierarchies

See the reference of classes :class:`Section` and :class:`Quantities` for details.

.. autoclass:: Section
.. autoclass:: Quantity
"""

# TODO validation

from typing import Type, TypeVar, Union, Tuple, Iterable, List, Any, Dict, Set, Callable, cast
from collections.abc import Iterable as IterableABC
import sys
import inspect
import re
import json
import itertools
import time

import numpy as np
from pint.unit import _Unit
from pint import UnitRegistry

start_time = time.time()
is_bootstrapping = True
MSectionBound = TypeVar('MSectionBound', bound='MSection')
T = TypeVar('T')


class MetainfoError(Exception):
    """ An error within the definition for metainfo data. """
    pass


# Reflection

class Enum(list):
    """ Allows to define str types with values limited to a pre-set list of possible values. """
    pass


class DataType:
    """
    Allows to define custom data types that can be used in the meta-info.

    The metainfo supports most types out of the box. These includes the python build-in
    primitive types (int, bool, str, float, ...), references to sections, and enums.
    However, in some occasions you need to add custom data types.
    """
    def type_check(self, section, value):
        """ Checks the given value before it is set to the given section. Can modify the value. """
        return value

    def to_json_serializable(self, section, value):
        return value

    def from_json_serializable(self, section, value):
        return value


class Dimension(DataType):
    def type_check(self, section, value):
        if isinstance(value, int):
            return value

        if isinstance(value, str):
            if value.isidentifier():
                return value
            if re.match(r'(\d)\.\.(\d|\*)', value):
                return value

        if isinstance(value, Section):
            return value

        if isinstance(value, type) and hasattr(value, 'm_def'):
            return value

        raise TypeError('%s is not a valid dimension' % str(value))


class Reference(DataType):
    """ A datatype class that can be used to define reference types based on section definitions.

    A quantity can be used to define possible references between sections. Instantiate
    this class to create a reference type that specified that a quantity with this type
    is actually a reference (or references, depending on shape) to a section of the
    given definition.
    """
    def __init__(self, section: 'Section'):
        self.section = section


class Unit(DataType):
    def type_check(self, section, value):
        if isinstance(value, str):
            value = units.parse_units(value)

        elif not isinstance(value, _Unit):
            raise TypeError('Units must be given as str or pint Unit instances.')

        return value

    def to_json_serializable(self, section, value):
        return value.__str__()

    def from_json_serializable(self, section, value):
        return units.parse_units(value)

# TODO class Datetime(DataType)


class MObjectMeta(type):

    def __new__(self, cls_name, bases, dct):
        cls = super().__new__(self, cls_name, bases, dct)

        init = getattr(cls, '__init_cls__')
        if init is not None and not is_bootstrapping:
            init()
        return cls


Content = Tuple['MSection', int, 'SubSection', 'MSection']

SectionDef = Union[str, 'Section', 'SubSection', Type[MSectionBound]]
""" Type for section definition references.

This can either be :

- the name of the section
- the section definition itself
- the definition of a sub section
- or the section definition Python class
"""


class MData:
    """ An interface for low-level metainfo data objects.

    Metainfo data objects store the data of a single section instance. This interface
    constitutes the minimal functionality for accessing and modifying section data.
    Different implementations of this interface, can realize different storage backends,
    or include different rigorosity of type and shape checks.

    All section instances will implement this interface, usually be delegating calls to
    a standalone implementation of this interface. This allows to configure various
    data backends on section instance creation.
    """

    def __getitem__(self, key):
        raise NotImplementedError()

    def __setitem__(self, key, value):
        raise NotImplementedError()

    def m_set(self, section: 'MSection', quantity_def: 'Quantity', value: Any) -> None:
        """ Set the given value for the given quantity. """
        raise NotImplementedError()

    def m_get(self, section: 'MSection', quantity_def: 'Quantity') -> Any:
        """ Retrieve the given value for the given quantity. """
        raise NotImplementedError()

    def m_is_set(self, section: 'MSection', quantity_def: 'Quantity') -> bool:
        """ True iff this quantity was explicitely set. """
        raise NotImplementedError()

    def m_add_values(
            self, section: 'MSection', quantity_def: 'Quantity', values: Any,
            offset: int) -> None:
        """ Add (partial) values for the given quantity of higher dimensionality. """
        raise NotImplementedError()

    def m_add_sub_section(
            self, section: 'MSection', sub_section_def: 'SubSection',
            sub_section: 'MSection') -> None:
        """ Adds the given section instance as a sub section of the given sub section definition. """
        raise NotImplementedError()

    def m_get_sub_section(
            self, section: 'MSection', sub_section_def: 'SubSection',
            index: int) -> 'MSection':
        """ Retrieves a single sub section of the given sub section definition. """
        raise NotImplementedError()

    def m_get_sub_sections(
            self, section: 'MSection', sub_section_def: 'SubSection') -> Iterable['MSection']:
        """ Retrieves  all sub sections of the given sub section definition. """
        raise NotImplementedError()

    def m_sub_section_count(self, section: 'MSection', sub_section_def: 'SubSection') -> int:
        """ Returns the number of sub sections for the given sub section definition. """
        raise NotImplementedError()


class MDataDelegating(MData):
    """ A simple delgating implementation of :class:`MData`. """
    def __init__(self, m_data: MData):
        self.m_data = m_data

    def __getitem__(self, key):
        return self.m_data[key]

    def __setitem__(self, key, value):
        self.m_data[key] = value

    def m_set(self, section: 'MSection', quantity_def: 'Quantity', value: Any) -> None:
        self.m_data.m_set(section, quantity_def, value)

    def m_get(self, section: 'MSection', quantity_def: 'Quantity') -> Any:
        return self.m_data.m_get(section, quantity_def)

    def m_is_set(self, section: 'MSection', quantity_def: 'Quantity') -> bool:
        return self.m_data.m_is_set(section, quantity_def)

    def m_add_values(
            self, section: 'MSection', quantity_def: 'Quantity', values: Any,
            offset: int) -> None:
        self.m_data.m_add_values(section, quantity_def, values, offset)

    def m_add_sub_section(
            self, section: 'MSection', sub_section_def: 'SubSection',
            sub_section: 'MSection') -> None:
        self.m_data.m_add_sub_section(section, sub_section_def, sub_section)

    def m_get_sub_section(
            self, section: 'MSection', sub_section_def: 'SubSection',
            index: int) -> 'MSection':
        return self.m_data.m_get_sub_section(section, sub_section_def, index)

    def m_get_sub_sections(
            self, section: 'MSection', sub_section_def: 'SubSection') -> Iterable['MSection']:
        return self.m_data.m_get_sub_sections(section, sub_section_def)

    def m_sub_section_count(self, section: 'MSection', sub_section_def: 'SubSection') -> int:
        return self.m_data.m_sub_section_count(section, sub_section_def)


class MDataDict(MData):
    """ A simple dict backed implementaton of :class:`MData`. """

    def __init__(self, dct: Dict[str, Any] = None):
        if dct is None:
            dct = {}

        self.dct = dct

    def __getitem__(self, key):
        return self.dct[key]

    def __setitem__(self, key, value):
        self.dct[key] = value

    def m_set(self, section: 'MSection', quantity_def: 'Quantity', value: Any) -> None:
        self.dct[quantity_def.name] = value

    def m_get(self, section: 'MSection', quantity_def: 'Quantity') -> Any:
        quantity_name = quantity_def.name
        if quantity_name not in self.dct:
            return quantity_def.default
        else:
            return self.dct[quantity_name]

    def m_is_set(self, section: 'MSection', quantity_def: 'Quantity') -> bool:
        return quantity_def.name in self.dct

    def m_add_values(
            self, section: 'MSection', quantity_def: 'Quantity', values: Any,
            offset: int) -> None:

        # TODO
        raise NotImplementedError()

    def m_add_sub_section(
            self, section: 'MSection', sub_section_def: 'SubSection',
            sub_section: 'MSection') -> None:

        sub_section_name = sub_section_def.name
        if sub_section_def.repeats:
            sub_section_lst = self.dct.get(sub_section_name, None)
            if sub_section_lst is None:
                sub_section_lst = self.dct.setdefault(sub_section_name, [])

            sub_section_lst.append(sub_section)

        else:
            self.dct[sub_section_name] = sub_section

    def m_get_sub_section(
            self, section: 'MSection', sub_section_def: 'SubSection',
            index: int) -> 'MSection':

        if sub_section_def.repeats:
            return self.dct[sub_section_def.name][index]

        else:
            return self.dct.get(sub_section_def.name, None)

    def m_get_sub_sections(
            self, section: 'MSection', sub_section_def: 'SubSection') -> Iterable['MSection']:
        return self.dct.get(sub_section_def.name, [])

    def m_sub_section_count(self, section: 'MSection', sub_section_def: 'SubSection') -> int:
        sub_section_name = sub_section_def.name
        if sub_section_name not in self.dct:
            return 0

        if not sub_section_def.repeats:
            return 1

        return len(self.dct[sub_section_name])


class MDataTypeAndShapeChecks(MDataDelegating):
    """ A :class:`MData` implementation that delegates to another :class:`MData`
    instance after applying rigorous type/checks. It might also resolve potential
    duck typed values, depending on quantity :class:`DataType`s.
    """

    def __init__(self, m_data: MData):
        self.m_data = m_data

    def __check_np(self, quantity_ref: 'Quantity', value: np.ndarray) -> np.ndarray:
        # TODO
        return value

    def __check_single(
            self, section: 'MSection', quantity_def: 'Quantity', value: Any) -> Any:

        if isinstance(quantity_def.type, DataType):
            return quantity_def.type.type_check(section, value)

        elif isinstance(quantity_def.type, Section):
            if not isinstance(value, MSection):
                raise TypeError(
                    'The value %s for reference quantity %s is not a section instance.' %
                    (value, quantity_def))

            if not value.m_follows(quantity_def.type):
                raise TypeError(
                    'The value %s for quantity %s does not follow %s' %
                    (value, quantity_def, quantity_def.type))

        elif isinstance(quantity_def.type, Enum):
            if value not in quantity_def.type:
                raise TypeError(
                    'The value %s is not an enum value for quantity %s.' %
                    (value, quantity_def))

        elif quantity_def == Quantity.type:
            # TODO check this special case of values used as quantity types
            pass

        elif quantity_def.type == Any:
            pass

        else:
            if type(value) != quantity_def.type:
                raise TypeError(
                    'The value %s with type %s for quantity %s is not of type %s' %
                    (value, type(value), quantity_def, quantity_def.type))

        return value

    def m_set(self, section: 'MSection', quantity_def: 'Quantity', value: Any) -> None:
        if type(quantity_def.type) == np.dtype:
            if type(value) != np.ndarray:
                try:
                    value = np.asarray(value)
                except TypeError:
                    raise TypeError(
                        'Could not convert value %s of %s to a numpy array' %
                        (value, quantity_def))

            value = self.__check_np(quantity_def, value)

        else:
            dimensions = len(quantity_def.shape)
            if dimensions == 0:
                value = self.__check_single(section, quantity_def, value)

            elif dimensions == 1:
                if type(value) == str or not isinstance(value, IterableABC):
                    raise TypeError(
                        'The shape of %s requires an iterable value, but %s is not iterable.' %
                        (quantity_def, value))

                value = list(self.__check_single(section, quantity_def, item) for item in value)

            else:
                raise MetainfoError(
                    'Only numpy arrays and dtypes can be used for higher dimensional '
                    'quantities.')

        self.m_data.m_set(section, quantity_def, value)


class MSection(metaclass=MObjectMeta):
    """Base class for all section instances on all meta-info levels.

    All metainfo objects instantiate classes that inherit from ``MSection``. Each
    section or quantity definition is an ``MSection``, each actual (meta-)data carrying
    section is an ``MSection``. This class consitutes the reflection interface of the
    meta-info, since it allows to manipulate sections (and therefore all meta-info data)
    without having to know the specific sub-class.

    It also carries all the data for each section. All sub-classes only define specific
    sections in terms of possible sub-sections and quantities. The data is managed here.

    The reflection insterface for reading and manipulating quantity values consists of
    Pythons build in ``getattr``, ``setattr``, and ``del``, as well as member functions
    :func:`m_add_value`, and :func:`m_add_values`.

    Sub-sections and parent sections can be read and manipulated with :data:`m_parent`,
    :func:`m_sub_section`, :func:`m_create`.

    .. code-block:: python

        system = run.m_create(System)
        assert system.m_parent == run
        assert run.m_sub_section(System, system.m_parent_index) == system

    Attributes:
        m_def: The section definition that defines this sections, its possible
            sub-sections and quantities.
        m_parent: The parent section instance that this section is a sub-section of.
        m_parent_sub_section: The sub section definition that holds this section in the parent.
        m_parent_index: For repeatable sections, parent keep a list of sub-sections for
            each section definition. This is the index of this section in the respective
            parent sub-section list.
        m_data: The dictionary that holds all data of this section. It keeps the quantity
            values and sub-section. It should only be read directly (and never manipulated)
            if you are know what you are doing. You should always use the reflection interface
            if possible.
    """

    m_def: 'Section' = None

    def __init__(self, m_def: 'Section' = None, m_data: MData = None, **kwargs):

        self.m_def: 'Section' = m_def
        self.m_parent: 'MSection' = None
        self.m_parent_sub_section: 'SubSection' = None
        self.m_parent_index = -1

        # get missing m_def from class
        cls = self.__class__
        if self.m_def is None:
            self.m_def = cls.m_def

        if cls.m_def is not None:
            assert self.m_def == cls.m_def, \
                'Section class and section definition must match'

        # get annotations from kwargs
        self.m_annotations: Dict[str, Any] = {}
        rest = {}
        for key, value in kwargs.items():
            if key.startswith('a_'):
                self.m_annotations[key[2:]] = value
            else:
                rest[key] = value

        # initialize data
        self.m_data = m_data
        if self.m_data is None:
            self.m_data = MDataTypeAndShapeChecks(MDataDict())

        # set remaining kwargs
        if is_bootstrapping:
            self.m_data.m_data.dct.update(**rest)  # type: ignore
        else:
            self.m_update(**rest)

    @classmethod
    def __init_cls__(cls):
        # ensure that the m_def is defined
        m_def = cls.m_def
        if m_def is None:
            m_def = Section()
            setattr(cls, 'm_def', m_def)

        # transfer name and description to m_def
        m_def.name = cls.__name__
        if cls.__doc__ is not None:
            m_def.description = inspect.cleandoc(cls.__doc__).strip()
        m_def.section_cls = cls

        for name, attr in cls.__dict__.items():
            # transfer names and descriptions for properties
            if isinstance(attr, Property):
                attr.name = name
                if attr.description is not None:
                    attr.description = inspect.cleandoc(attr.description).strip()
                    attr.__doc__ = attr.description

                if isinstance(attr, Quantity):
                    m_def.m_add_sub_section(Section.quantities, attr)
                elif isinstance(attr, SubSection):
                    m_def.m_add_sub_section(Section.sub_sections, attr)
                else:
                    raise NotImplementedError('Unknown property kind.')

        # add base sections
        for base_cls in cls.__bases__:
            if base_cls != MSection:
                base_section = getattr(base_cls, 'm_def')
                if base_section is None:
                    raise TypeError(
                        'Section defining classes must have MSection or a decendant as '
                        'base classes.')

                base_sections = list(m_def.m_get(Section.base_sections))
                base_sections.append(base_section)
                m_def.m_set(Section.base_sections, base_sections)

        # add section cls' section to the module's package
        module_name = cls.__module__
        pkg = Package.from_module(module_name)
        pkg.m_add_sub_section(Package.section_definitions, cls.m_def)

    def __resolve_synonym(self, quantity_def: 'Quantity') -> 'Quantity':
        if quantity_def.synonym_for is not None:
            return self.m_def.all_quantities[quantity_def.synonym_for]
        return quantity_def

    def m_set(self, quantity_def: 'Quantity', value: Any) -> None:
        """ Set the given value for the given quantity. """
        quantity_def = self.__resolve_synonym(quantity_def)
        self.m_data.m_set(self, quantity_def, value)

    def m_get(self, quantity_def: 'Quantity') -> Any:
        """ Retrieve the given value for the given quantity. """
        quantity_def = self.__resolve_synonym(quantity_def)
        return self.m_data.m_get(self, quantity_def)

    def m_is_set(self, quantity_def: 'Quantity') -> bool:
        quantity_def = self.__resolve_synonym(quantity_def)
        return self.m_data.m_is_set(self, quantity_def)

    def m_add_values(self, quantity_def: 'Quantity', values: Any, offset: int) -> None:
        """ Add (partial) values for the given quantity of higher dimensionality. """
        self.m_data.m_add_values(self, quantity_def, values, offset)

    def m_add_sub_section(self, sub_section_def: 'SubSection', sub_section: 'MSection') -> None:
        """ Adds the given section instance as a sub section of the given sub section definition. """

        parent_index = -1
        if sub_section_def.repeats:
            parent_index = self.m_sub_section_count(sub_section_def)
        sub_section.m_parent = self
        sub_section.m_parent_sub_section = sub_section_def
        sub_section.m_parent_index = parent_index

        self.m_data.m_add_sub_section(self, sub_section_def, sub_section)

    def m_get_sub_section(self, sub_section_def: 'SubSection', index: int) -> 'MSection':
        """ Retrieves a single sub section of the given sub section definition. """
        return self.m_data.m_get_sub_section(self, sub_section_def, index)

    def m_get_sub_sections(self, sub_section_def: 'SubSection') -> Iterable['MSection']:
        """ Retrieves  all sub sections of the given sub section definition. """
        return self.m_data.m_get_sub_sections(self, sub_section_def)

    def m_sub_section_count(self, sub_section_def: 'SubSection') -> int:
        """ Returns the number of sub sections for the given sub section definition. """
        return self.m_data.m_sub_section_count(self, sub_section_def)

    def m_create(self, section_cls: Type[MSectionBound], **kwargs) -> MSectionBound:
        """ Creates a section instance and adds it to this section provided there is a
        corresponding sub section.
        """

        section_def = section_cls.m_def
        sub_section_def = self.m_def.all_sub_sections_by_section.get(section_def, None)
        if sub_section_def is None:
            raise TypeError('There is not sub section for %s in %s.' % (section_def, self))

        sub_section = section_cls(**kwargs)
        self.m_add_sub_section(sub_section_def, sub_section)

        return cast(MSectionBound, sub_section)

    def m_update(self, **kwargs):
        """ Updates all quantities and sub-sections with the given arguments. """
        for name, value in kwargs.items():
            prop = self.m_def.all_properties.get(name, None)
            if prop is None:
                raise KeyError('%s is not an attribute of this section %s' % (name, self))

            if isinstance(prop, SubSection):
                if prop.repeats:
                    if isinstance(value, List):
                        for item in value:
                            self.m_add_sub_section(prop, item)
                    else:
                        raise TypeError('Sub section %s repeats, but no list was given' % prop.name)
                else:
                    self.m_add_sub_section(prop, item)

            else:
                self.m_set(prop, value)

    def m_follows(self, definition: 'Section') -> bool:
        """ Determines if this section's definition is or is derived from the given definition. """
        return self.m_def == definition or self.m_def in definition.all_base_sections

    def m_to_dict(self) -> Dict[str, Any]:
        """Returns the data of this section as a json serializeable dictionary. """

        def items() -> Iterable[Tuple[str, Any]]:
            yield 'm_def', self.m_def.name
            if self.m_parent_index != -1:
                yield 'm_parent_index', self.m_parent_index

            for name, sub_section_def in self.m_def.all_sub_sections.items():
                if sub_section_def.repeats:
                    if self.m_sub_section_count(sub_section_def) > 0:
                        yield name, [
                            item.m_to_dict()
                            for item in self.m_get_sub_sections(sub_section_def)]
                else:
                    sub_section = self.m_get_sub_section(sub_section_def, -1)
                    if sub_section is not None:
                        yield name, sub_section.m_to_dict()

            for name, quantity in self.m_def.all_quantities.items():
                if self.m_is_set(quantity):
                    to_json_serializable: Callable[[Any], Any] = str
                    if isinstance(quantity.type, DataType):

                        def serialize(v):
                            quantity.type.to_json_serializable(self, v)

                        to_json_serializable = serialize

                    elif isinstance(quantity.type, Section):
                        # TODO
                        to_json_serializable = str
                    elif quantity.type in [str, int, float, bool]:
                        to_json_serializable = quantity.type

                    else:
                        # TODO
                        pass

                    value = getattr(self, name)

                    if hasattr(value, 'tolist'):
                        serializable_value = value.tolist()

                    else:
                        if len(quantity.shape) == 0:
                            serializable_value = to_json_serializable(value)
                        elif len(quantity.shape) == 1:
                            serializable_value = [to_json_serializable(i) for i in value]
                        else:
                            raise NotImplementedError('Higher shapes (%s) not supported: %s' % (quantity.shape, quantity))

                    yield name, serializable_value

        return {key: value for key, value in items()}

    @classmethod
    def m_from_dict(cls: Type[MSectionBound], dct: Dict[str, Any]) -> MSectionBound:
        """ Creates a section from the given data dictionary.

        This is the 'oposite' of :func:`m_to_dict`. It takes a deserialized dict, e.g
        loaded from JSON, and turns it into a proper section, i.e. instance of the given
        section class.
        """

        section_def = cls.m_def

        # remove m_def and m_parent_index, they set themselves automatically
        assert section_def.name == dct.pop('m_def', None)
        dct.pop('m_parent_index', -1)

        def items():
            for name, sub_section_def in section_def.all_sub_sections.items():
                if name in dct:
                    sub_section_value = dct.pop(name)
                    if sub_section_def.repeats:
                        yield name, [
                            sub_section_def.sub_section.section_cls.m_from_dict(sub_section_dct)
                            for sub_section_dct in sub_section_value]
                    else:
                        yield name, sub_section_def.sub_section.section_cls.m_from_dict(sub_section_value)

            for key, value in dct.items():
                yield key, value

        dct = {key: value for key, value in items()}
        section_instance = cast(MSectionBound, section_def.section_cls())
        section_instance.m_update(**dct)
        return section_instance

    def m_to_json(self, **kwargs):
        """Returns the data of this section as a json string. """
        return json.dumps(self.m_to_dict(), **kwargs)

    def m_all_contents(self) -> Iterable[Content]:
        """Returns an iterable over all sub and sub subs sections. """
        for content in self.m_contents():
            for sub_content in content[0].m_all_contents():
                yield sub_content

            yield content

    def m_contents(self) -> Iterable[Content]:
        """Returns an iterable over all direct subs sections. """
        for sub_section_def in self.m_def.all_sub_sections.values():
            if sub_section_def.repeats:
                index = 0
                for sub_section in self.m_get_sub_sections(sub_section_def):
                    yield sub_section, index, sub_section_def, self
                    index += 1

            else:
                sub_section = self.m_get_sub_section(sub_section_def, -1)
                yield sub_section, -1, sub_section_def, self

    def __repr__(self):
        m_section_name = self.m_def.name
        # name_quantity_def = self.m_def.all_quantities.get('name', None)
        # if name_quantity_def is not None:
        #     name = self.m_get(name_quantity_def)
        try:
            name = self.m_data['name']
        except KeyError:
            name = '<noname>'

        return '%s:%s' % (name, m_section_name)


class MCategory(metaclass=MObjectMeta):

    m_def: 'Category' = None

    @classmethod
    def __init_cls__(cls):
        # ensure that the m_def is defined
        m_def = cls.m_def
        if m_def is None:
            m_def = Category()
            setattr(cls, 'm_def', m_def)

        # transfer name and description to m_def
        m_def.name = cls.__name__
        if cls.__doc__ is not None:
            m_def.description = inspect.cleandoc(cls.__doc__).strip()

        # add section cls' section to the module's package
        module_name = cls.__module__
        pkg = Package.from_module(module_name)
        pkg.m_add_sub_section(Package.category_definitions, cls.m_def)


# M3, the definitions that are used to write definitions. These are the section definitions
# for sections Section and Quantity.They define themselves; i.e. the section definition
# for Section is the same section definition.
# Due to this circular nature (hen-egg-problem), the classes for sections Section and
# Quantity do only contain placeholder for their own section and quantity definitions.
# These placeholder are replaced, once the necessary classes are defined. This process
# is referred to as 'bootstrapping'.

_definition_change_counter = 0


class cached_property:
    """ A property that allows to cache the property value.

    The cache will be invalidated whenever a new definition is added. Once all definitions
    are loaded, the cache becomes stable and complex derived results become available
    instantaneous.
    """
    def __init__(self, f):
        self.__doc__ = getattr(f, "__doc__")
        self.f = f
        self.change = -1
        self.values: Dict[type(self), Any] = {}

    def __get__(self, obj, cls):
        if obj is None:
            return self

        global _definition_change_counter
        if self.change != _definition_change_counter:
            self.values = {}

        value = self.values.get(obj, None)
        if value is None:
            value = self.f(obj)
            self.values[obj] = value

        return value


class Definition(MSection):

    __all_definitions: Dict[Type[MSection], List[MSection]] = {}

    name: 'Quantity' = None
    description: 'Quantity' = None
    links: 'Quantity' = None
    categories: 'Quantity' = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        global _definition_change_counter
        _definition_change_counter += 1

        for cls in self.__class__.mro() + [self.__class__]:
            definitions = Definition.__all_definitions.setdefault(cls, [])
            definitions.append(self)

    @classmethod
    def all_definitions(cls: Type[MSectionBound]) -> Iterable[MSectionBound]:
        """ Returns all definitions of this definition class. """
        return cast(Iterable[MSectionBound], Definition.__all_definitions.get(cls, []))

    @cached_property
    def all_categories(self):
        """ All categories of this definition and its categories. """
        all_categories = list(self.categories)
        for category in self.categories:  # pylint: disable=not-an-iterable
            for super_category in category.all_categories:
                all_categories.append(super_category)

        return all_categories


class Property(Definition):
    pass


class Quantity(Property):
    """Used to define quantities that store a certain piece of (meta-)data.

    Quantities are the basic building block with meta-info data. The Quantity class is
    used to define quantities within sections. A quantity definition
    is a (physics) quantity with name, type, shape, and potentially a unit.

    In Python terms, quantities are descriptors. Descriptors define how to get, set, and
    delete values for a object attribute. Meta-info descriptors ensure that
    type and shape fit the set values.
    """

    type: 'Quantity' = None
    shape: 'Quantity' = None
    unit: 'Quantity' = None
    default: 'Quantity' = None
    synonym_for: 'Quantity' = None

    # TODO derived_from = Quantity(type=Quantity, shape=['0..*'])
    # TODO categories = Quantity(type=Category, shape=['0..*'])
    # TODO converter = Quantity(type=Converter), a class with set of functions for
    #      normalizing, (de-)serializing values.

    def __get__(self, obj, cls):
        if obj is None:
            # class (def) attribute case
            return self

        return obj.m_get(self)

    def __set__(self, obj, value):
        if obj is None:
            # class (def) case
            raise KeyError('Cannot overwrite quantity definition. Only values can be set.')

        # object (instance) case
        obj.m_set(self, value)

    def __delete__(self, obj):
        if obj is None:
            # class (def) case
            raise KeyError('Cannot delete quantity definition. Only values can be deleted.')

        # object (instance) case
        raise NotImplementedError('Deleting quantity values is not supported.')


class DirectQuantity(Quantity):
    """ Used for quantities that would cause indefinite loops due to bootstrapping. """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__name = kwargs.get('name')
        self.__default = kwargs.get('default')

    def __get__(self, obj, cls):
        if obj is None:
            # class (def) attribute case
            return self

        try:
            return obj.m_data[self.__name]
        except KeyError:
            return self.__default

    def __set__(self, obj, value):
        if obj is None:
            # class (def) case
            raise KeyError('Cannot overwrite quantity definition. Only values can be set.')

        # object (instance) case
        obj.m_data[self.__name] = value


class SubSection(Property):
    """ Allows to assign a section class as a sub-section to another section class. """

    sub_section: 'Quantity' = None
    repeats: 'Quantity' = None

    def __get__(self, obj, type=None):
        if obj is None:
            # the class attribute case
            return self

        else:
            # the object attribute case
            if self.repeats:
                return obj.m_get_sub_sections(self)
            else:
                return obj.m_get_sub_section(self, -1)

    def __set__(self, obj, value):
        raise NotImplementedError('Sub sections cannot be set directly. Use m_create.')

    def __delete__(self, obj):
        raise NotImplementedError('Deleting sub sections is not supported.')


class Section(Definition):
    """Used to define section that organize meta-info data into containment hierarchies.

    Section definitions determine what quantities and sub-sections can appear in a section
    instance.

    In Python terms, sections are classes. Sub-sections and quantities are attributes of
    respective instantiating objects. For each section class there is a corresponding
    :class:`Section` instance that describes this class as a section. This instance
    is referred to as 'section definition' in contrast to the Python class that we call
    'section class'.
    """

    section_cls: Type[MSection] = None
    """ The section class that corresponse to this section definition. """

    quantities: 'SubSection' = None
    sub_sections: 'SubSection' = None

    base_sections: 'Quantity' = None
    # TODO extends = Quantity(type=bool), denotes this section as a container for
    #      new quantities that belong to the base-class section definitions
    @cached_property
    def all_base_sections(self) -> Set['Section']:
        all_base_sections: Set['Section'] = set()
        for base_section in self.base_sections:  # pylint: disable=not-an-iterable
            all_base_sections.add(base_section)

            for base_base_section in base_section.all_base_sections:
                all_base_sections.add(base_base_section)

        return all_base_sections

    @cached_property
    def all_properties(self) -> Dict[str, Union['SubSection', Quantity]]:
        """ All attribute (sub section and quantity) definitions. """

        properties: Dict[str, Union[SubSection, Quantity]] = dict(**self.all_quantities)
        properties.update(**self.all_sub_sections)
        return properties

    @cached_property
    def all_quantities(self) -> Dict[str, Quantity]:
        """ All quantity definition in the given section definition. """

        all_quantities: Dict[str, Quantity] = {}
        for section in itertools.chain(self.all_base_sections, [self]):
            for quantity in section.m_get_sub_sections(Section.quantities):
                all_quantities[quantity.name] = quantity

        return all_quantities

    @cached_property
    def all_sub_sections(self) -> Dict[str, 'SubSection']:
        """ All sub section definitions for this section definition by name. """

        all_sub_sections: Dict[str, SubSection] = {}
        for section in itertools.chain(self.all_base_sections, [self]):
            for sub_section in section.m_get_sub_sections(Section.sub_sections):
                all_sub_sections[sub_section.name] = sub_section

        return all_sub_sections

    @cached_property
    def all_sub_sections_by_section(self) -> Dict['Section', 'SubSection']:
        """ All sub section definitions for this section definition by their section definition. """

        all_sub_sections: Dict[Section, SubSection] = {}
        for section in itertools.chain(self.all_base_sections, [self]):
            for sub_section in section.m_get_sub_sections(Section.sub_sections):
                all_sub_sections[sub_section.sub_section] = sub_section

        return all_sub_sections


class Package(Definition):

    section_definitions: 'SubSection' = None
    category_definitions: 'SubSection' = None

    @staticmethod
    def from_module(module_name: str):
        module = sys.modules[module_name]

        pkg: 'Package' = getattr(module, 'm_package', None)
        if pkg is None:
            pkg = Package()
            setattr(module, 'm_package', pkg)

        pkg.name = module_name
        if pkg.description is None and module.__doc__ is not None:
            pkg.description = inspect.cleandoc(module.__doc__).strip()

        return pkg


class Category(Definition):
    """Can be used to define categories for definitions.

    Each definition, including categories themselves, can belong to a set of categories.
    Categories therefore form a hierarchy of concepts that definitions can belong to, i.e.
    they form a `is a` relationship.

    In the old meta-info this was known as `abstract types`.
    """

    @cached_property
    def definitions(self) -> Iterable[Definition]:
        """ All definitions that are directly or indirectly in this category. """
        return list([
            definition for definition in Definition.all_definitions()
            if self in definition.all_categories])


Section.m_def = Section(name='Section')
Section.m_def.m_def = Section.m_def
Section.m_def.section_cls = Section

Definition.m_def = Section(name='Definition')
Property.m_def = Section(name='Property')
Quantity.m_def = Section(name='Quantity')
SubSection.m_def = Section(name='SubSection')
Category.m_def = Section(name='Category')
Package.m_def = Section(name='Package')

Definition.name = DirectQuantity(
    type=str, name='name', description='''
    The name of the quantity. Must be unique within a section.
    ''')
Definition.description = Quantity(
    type=str, name='description', description='''
    An optional human readable description.
    ''')
Definition.links = Quantity(
    type=str, shape=['0..*'], name='links', description='''
    A list of URLs to external resource that describe this definition.
    ''')
Definition.categories = Quantity(
    type=Category.m_def, shape=['0..*'], default=[], name='categories',
    description='''
    The categories that this definition belongs to. See :class:`Category`.
    ''')

Section.quantities = SubSection(
    sub_section=Quantity.m_def, name='quantities', repeats=True,
    description='''The quantities of this section.''')

Section.sub_sections = SubSection(
    sub_section=SubSection.m_def, name='sub_sections', repeats=True,
    description='''The sub sections of this section.''')
Section.base_sections = Quantity(
    type=Section, shape=['0..*'], default=[], name='base_sections',
    description='''
    Inherit all quantity and sub section definitions from the given sections.
    Will be derived from Python base classes.
    ''')


SubSection.repeats = Quantity(
    type=bool, name='repeats', default=False,
    description='''Wether this sub section can appear only once or multiple times. ''')

SubSection.sub_section = Quantity(
    type=Section.m_def, name='sub_section', description='''
    The section definition for the sub section. Only section instances of this definition
    can be contained as sub sections.
    ''')

Quantity.m_def.section_cls = Quantity
Quantity.type = Quantity(
    type=Union[type, Enum, Section, np.dtype], name='type', description='''
    The type of the quantity.

    Can be one of the following:

    - none to support any value
    - a build-in primitive Python type, e.g. ``int``, ``str``
    - an instance of :class:`Enum`, e.g. ``Enum(['one', 'two', 'three'])
    - a instance of Section, i.e. a section definition. This will define a reference
    - a custom meta-info DataType
    - a numpy dtype,

    If set to a dtype, this quantity will use a numpy array to store values. It will use
    the given dtype. If not set, this quantity will use (nested) Python lists to store values.
    If values are set to the property, they will be converted to the respective
    representation.

    In the NOMAD CoE meta-info this was basically the ``dTypeStr``.
    ''')
Quantity.shape = Quantity(
    type=Dimension(), shape=['0..*'], name='shape', default=[], description='''
    The shape of the quantity that defines its dimensionality.

    A shape is a list, where each item defines a dimension. Each dimension can be:

    - an integer that defines the exact size of the dimension, e.g. ``[3]`` is the
      shape of a spacial vector
    - the name of an int typed quantity in the same section
    - a range specification as string build from a lower bound (i.e. int number),
      and an upper bound (int or ``*`` denoting arbitrary large), e.g. ``'0..*'``, ``'1..3'``
    ''')
Quantity.unit = Quantity(
    type=Unit(), name='unit', description='''
    The optional physics unit for this quantity.

    Units are given in `pint` units. Pint is a Python package that defines units and
    their algebra. There is a default registry :data:`units` that you can use.
    Example units are: ``units.m``, ``units.m / units.s ** 2``.
    ''')
Quantity.default = DirectQuantity(
    type=Any, default=None, name='default', description='''
    The default value for this quantity.
    ''')
Quantity.synonym_for = DirectQuantity(
    type=str, name='synonym_for', description='''
    With this set, the quantitiy will become a virtual quantity and its data is not stored
    directly. Setting and getting quantity, will change the *synonym* quantity instead. Use
    the name of the quantity as value.
    ''')

Package.section_definitions = SubSection(
    sub_section=Section.m_def, name='section_definitions', repeats=True,
    description=''' The sections defined in this package. ''')

Package.category_definitions = SubSection(
    sub_section=Category.m_def, name='category_definitions', repeats=True,
    description=''' The categories defined in this package. ''')

is_bootstrapping = False

Package.__init_cls__()
Definition.__init_cls__()
Property.__init_cls__()
Category.__init_cls__()
Section.__init_cls__()
SubSection.__init_cls__()
Quantity.__init_cls__()

print('Metainfo initialization took %d ms' % ((time.time() - start_time) * 1000))

units = UnitRegistry()
""" The default pint unit registry that should be used to give units to quantity definitions. """