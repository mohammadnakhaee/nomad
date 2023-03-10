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
After parsing entries have to be normalized with a set of *normalizers*.
In NOMAD-coe those were programmed in python (we'll reuse) and scala (we'll rewrite).

Currently the normalizers are:
- system.py (contains aspects of format stats, system, system type, and symmetry normalizer)
- optimade.py
- fhiaims.py
- dos.py

The normalizers are available via

.. autodata:: nomad.normalizing.normalizers

There is one ABC for all normalizer:

.. autoclass::nomad.normalizing.normalizer.Normalizer
    :members:
'''

from typing import List, Any, Iterable, Type

from .system import SystemNormalizer
from .optimade import OptimadeNormalizer
from .dos import DosNormalizer
from .normalizer import Normalizer
from .band_structure import BandStructureNormalizer
from .workflow import WorkflowNormalizer
from .results import ResultsNormalizer
from .metainfo import MetainfoNormalizer
from .workflow2 import WorkflowNormalizer as Workflow2Normalizer

normalizers: Iterable[Type[Normalizer]] = [
    SystemNormalizer,
    OptimadeNormalizer,
    DosNormalizer,
    BandStructureNormalizer,
    WorkflowNormalizer,
    Workflow2Normalizer,
    ResultsNormalizer,
    MetainfoNormalizer
]
