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

from abc import ABCMeta, abstractmethod
from typing import List

from nomad.parsing import Backend
from nomad.utils import get_logger
from nomad.metainfo import MSection


class Normalizer(metaclass=ABCMeta):
    '''
    A base class for normalizers. Normalizers work on a :class:`Backend` instance
    for read and write. Normalizer instances are reused.

    Arguments:
        backend: The backend used to read and write data from and to.
    '''

    domain = 'dft'
    ''' The domain this normalizer should be used in. Default for all normalizer is 'DFT'. '''

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        try:
            self.section_run = backend.entry_archive.section_run[0]
        except (AttributeError, IndexError):
            self.section_run = None
        self.logger = get_logger(__name__)

    @abstractmethod
    def normalize(self, logger=None) -> None:
        if logger is not None:
            self.logger = logger.bind(normalizer=self.__class__.__name__)


class SystemBasedNormalizer(Normalizer, metaclass=ABCMeta):
    '''
    A normalizer base class for normalizers that only touch a section_system.

    The normalizer is run on all section systems in a run. However, some systems,
    selected by heuristic, are more `representative systems` for the run. Sub-classes
    might opt to do additional work for the `representative systems`.

    Args:
        only_representatives: Will only normalize the `representative` systems.
    '''
    def __init__(self, backend: Backend, only_representatives: bool = False):
        super().__init__(backend)
        self.only_representatives = only_representatives

    @property
    def quantities(self) -> List[str]:
        return [
            'atom_labels',
            'atom_positions',
            'atom_atom_numbers',
            'lattice_vectors',
            'simulation_cell',
            'configuration_periodic_dimensions'
        ]

    def _normalize_system(self, system, is_representative):
        context = '/section_run/0/section_system/%d' % system.m_parent_index

        self._backend.openContext(context)
        try:
            return self.normalize_system(system, is_representative)
        finally:
            self._backend.closeContext(context)

    @abstractmethod
    def normalize_system(self, system: MSection, is_representative: bool) -> bool:
        ''' Normalize the given section and returns True, iff successful'''
        pass

    def __representative_system(self):
        '''Used to select a representative system for this entry.

        Attempt to find a single section_system that is representative for the
        entry. The selection depends on the type of calculation.
        '''
        system = None
        scc_idx = None
        scc = None

        # Try to find a frame sequence, only first found is considered
        try:
            frame_seqs = self.section_run.section_frame_sequence
            frame_seq = frame_seqs[0]
            sec_sampling_method = frame_seq.frame_sequence_to_sampling_ref
            sampling_method = sec_sampling_method.sampling_method
            frames = frame_seq.frame_sequence_local_frames_ref
            if sampling_method == "molecular_dynamics":
                scc = frames[0]
                scc_idx = scc.m_parent_index
            else:
                scc = frames[-1]
                scc_idx = scc.m_parent_index
            system = scc.single_configuration_calculation_to_system_ref
            if system is None:
                frame_seqs = []
        except Exception:
            frame_seqs = []

        # If no frame sequences detected, try to find scc
        if len(frame_seqs) == 0:
            try:
                sccs = self.section_run.section_single_configuration_calculation
                scc_idx = -1
                scc = sccs[scc_idx]
                system = scc.single_configuration_calculation_to_system_ref
                if system is None:
                    sccs = []
            except Exception:
                sccs = []

            # If no sccs exist, try to find systems
            if len(sccs) == 0:
                try:
                    systems = self.section_run.section_system
                    system = systems[-1]
                except Exception:
                    sccs = []

            if system is None:
                self.logger.error('no "representative" section system found')
            else:
                self.logger.info(
                    'chose "representative" system for normalization',
                )

        if scc is not None:
            self.section_run.m_cache["representative_scc_idx"] = scc_idx
        if system is not None:
            self.section_run.m_cache["representative_system_idx"] = system.m_parent_index

        return system

    def __normalize_system(self, system, representative, logger=None) -> bool:
        try:
            return self._normalize_system(system, representative)

        except KeyError as e:
            self.logger.error(
                'could not read a system property', normalizer=self.__class__.__name__,
                section='section_system', g_index=system.m_parent_index, key_error=str(e), exc_info=e)
            return False

        except Exception as e:
            self.logger.error(
                'Unexpected error during normalizing', normalizer=self.__class__.__name__,
                section='section_system', g_index=system.m_parent_index, exc_info=e, error=str(e))
            raise e

    def normalize(self, logger=None) -> None:
        super().normalize(logger)

        # If no section run detected, do nothing
        if self.section_run is None:
            return

        # Process representative system first
        repr_sys_idx = None
        repr_sys = self.__representative_system()
        if repr_sys is not None:
            repr_sys_idx = repr_sys.m_parent_index
            self.logger.info('chose "representative" section system')
            self.__normalize_system(repr_sys, True, logger)

        # All the rest if requested
        if not self.only_representatives:
            for isys, system in enumerate(self._backend.entry_archive.section_run[0].section_system):
                if isys != repr_sys_idx:
                    self.__normalize_system(system, False, logger)
