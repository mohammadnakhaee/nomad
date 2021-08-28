#
# Copyright The NOMAD Authors.
#
# This file is part of NOMAD. See https://nomad-lab.eu for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import numpy as np            # pylint: disable=unused-import
import typing                 # pylint: disable=unused-import
from nomad.metainfo import (  # pylint: disable=unused-import
    MSection, MCategory, Category, Package, Quantity, Section, SubSection, SectionProxy,
    Reference, MEnum, derived)
from nomad.datamodel.metainfo.run.method import Method
from nomad.datamodel.metainfo.run.system import System
from nomad.datamodel.metainfo.run.calculation import Calculation


m_package = Package()


class AccessoryInfo(MCategory):
    '''
    Information that *in theory* should not affect the results of the calculations (e.g.,
    timing).
    '''

    m_def = Category()


class ProgramInfo(MCategory):
    '''
    Contains information on the program that generated the data, i.e. the program_name,
    program_version, program_compilation_host and program_compilation_datetime as direct
    children of this field.
    '''

    m_def = Category(categories=[AccessoryInfo])


class Program(MSection):
    '''
    Contains the specifications of the program.
    '''

    m_def = Section(validate=False)

    name = Quantity(
        type=str,
        shape=[],
        description='''
        Specifies the name of the program that generated the data.
        ''',
        categories=[AccessoryInfo, ProgramInfo])

    version = Quantity(
        type=str,
        shape=[],
        description='''
        Specifies the version of the program that was used. This should be the version
        number of an official release, the version tag or a commit id as well as the
        location of the repository.
        ''',
        categories=[AccessoryInfo, ProgramInfo])

    compilation_datetime = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Contains the program compilation date and time from *Unix epoch* (00:00:00 UTC on
        1 January 1970) in seconds. For date and times without a timezone, the default
        timezone GMT is used.
        ''',
        categories=[AccessoryInfo, ProgramInfo])

    compilation_host = Quantity(
        type=str,
        shape=[],
        description='''
        Specifies the host on which the program was compiled.
        ''',
        categories=[AccessoryInfo, ProgramInfo])


class TimeRun(MSection):
    '''
    Contains information on timing information of the run.
    '''

    m_def = Section(validate=False)

    date_end = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Stores the end date of the run as time since the *Unix epoch* (00:00:00 UTC on 1
        January 1970) in seconds. For date and times without a timezone, the default
        timezone GMT is used.
        ''')

    date_start = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Stores the start date of the run as time since the *Unix epoch* (00:00:00 UTC on 1
        January 1970) in seconds. For date and times without a timezone, the default
        timezone GMT is used.
        ''')

    cpu1_end = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Stores the end time of the run on CPU 1.
        ''')

    cpu1_start = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Stores the start time of the run on CPU 1.
        ''')

    wall_end = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Stores the internal wall-clock time at the end of the run.
        ''')

    wall_start = Quantity(
        type=np.dtype(np.float64),
        shape=[],
        unit='second',
        description='''
        Stores the internal wall-clock time from the start of the run.
        ''')


class MessageRun(MSection):
    '''
    Contains warning, error, and info messages of the run.
    '''

    m_def = Section(validate=False)

    type = Quantity(
        type=str,
        shape=[],
        description='''
        Type of the message. Can be one of warning, error, info, debug.
        ''')

    value = Quantity(
        type=str,
        shape=[],
        description='''
        Value of the message of the computational program, given by type.
        ''')


class RunReference(MSection):
    '''
    Section that describes the relationship between the current section to other run
    sections.

    The kind of relationship between the the current section and the referenced section
    run is described by kind. The referenced section is given by value (typically used for
    a run section in the same archive) or external_url.
    '''

    m_def = Section(validate=False)

    external_url = Quantity(
        type=str,
        shape=[],
        description='''
        URL used to reference an externally stored run section.
        ''')

    kind = Quantity(
        type=str,
        shape=[],
        description='''
        Defines the kind of relationship between the referenced section run with the
        present section.
        ''')

    value = Quantity(
        type=Reference(SectionProxy('Run')),
        shape=[],
        description='''
        Value of the referenced section run.
        ''')


class Run(MSection):
    '''
    Every section run represents a single call of a program.
    '''

    m_def = Section(validate=False)

    calculation_file_uri = Quantity(
        type=str,
        shape=[],
        description='''
        Contains the nomad uri of a raw the data file connected to the current run. There
        should be an value for the main_file_uri and all ancillary files.
        ''')

    clean_end = Quantity(
        type=bool,
        shape=[],
        description='''
        Indicates whether this run terminated properly (true), or if it was killed or
        exited with an error code unequal to zero (false).
        ''')

    raw_id = Quantity(
        type=str,
        shape=[],
        description='''
        An optional calculation id, if one is found in the code input/output files.
        ''')

    program = SubSection(sub_section=Program.m_def)

    time_run = SubSection(sub_section=TimeRun.m_def)

    message = SubSection(sub_section=MessageRun.m_def)

    method = SubSection(sub_section=Method.m_def, repeats=True)

    system = SubSection(sub_section=System.m_def, repeats=True)

    calculation = SubSection(sub_section=Calculation.m_def, repeats=True)

    run_ref = SubSection(sub_section=RunReference.m_def, repeats=True)


m_package.__init_metainfo__()
