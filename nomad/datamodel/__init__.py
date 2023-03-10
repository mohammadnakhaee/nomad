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

'''
Introduction
------------

This is about the *datamodel* that is used to represent NOMAD entries in our databases and
search engines. The respective data, also known as (repository) metadata is also part of
the NOMAD Archive and the datamodel is also defined based on the NOMAD Metainfo
(section *metadata*). It covers all information that users can search for and that can
be easily rendered on the GUI. The information is readily available through the
**repo** API.

.. image:: assets/data.png

See also the `datamodel section in the introduction <introduction.html#data-model>`_.

This module contains classes that allow to represent the core
nomad data entities (entries, users, datasets) on a high level of abstraction
independent from their representation in the different modules
:py:mod:`nomad.processing`, :py:mod:`nomad.parsing`, :py:mod:`nomad.search`, :py:mod:`nomad.app`.

Datamodel entities
------------------

The entities in the datamodel are defined as NOMAD Metainfo sections. They are treated
similarily to all Archive data. The entry datamodel data is created during
processing. It is not about representing every detail, but those parts that are directly involved in
api, processing, mirroring, or other 'infrastructure' operations.

The class :class:`User` is used to represent users and their attributes.

.. autoclass:: nomad.datamodel.User
    :members:

The class :class:`Dataset` is used to represent datasets and their attributes.

.. autoclass:: nomad.datamodel.Dataset
    :members:

The class :class:`EntryMetadata` is used to represent all metadata about an entry.

.. autoclass:: nomad.datamodel.EntryMetadata
    :members:

Domains
------------------

The datamodel supports different *domains*. This means that most domain metadata of an
entry is stored in domain-specific sub sections of the :class:`EntryMetadata`
section. We currently have the following domain specific metadata classes/sections:

.. autoclass:: nomad.datamodel.OptimadeEntry
    :members:
'''
import sys

from nomad.metainfo import Environment
from .data import (User, Author, user_reference, author_reference)
from .datamodel import (
    Dataset, EditableUserMetadata, AuthLevel,
    MongoUploadMetadata, MongoEntryMetadata, MongoSystemMetadata,
    EntryMetadata, EntryArchive)
from .optimade import OptimadeEntry, Species
from .metainfo import m_env
from .results import Results
from .data import EntryData, ArchiveSection
from .context import Context, ClientContext, ServerContext

m_env.m_add_sub_section(Environment.packages, sys.modules['nomad.datamodel.datamodel'].m_package)  # type: ignore
m_env.m_add_sub_section(Environment.packages, sys.modules['nomad.datamodel.optimade'].m_package)  # type: ignore
