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

import functools
import fractions
import itertools
from math import gcd as gcd
from functools import reduce
from typing import List, Dict, Tuple, Any, Union

import numpy as np
from scipy.spatial import Voronoi  # pylint: disable=no-name-in-module
from matid.symmetry import WyckoffSet

from nomad.aflow_prototypes import aflow_prototypes
from nomad.constants import atomic_masses


def get_summed_atomic_mass(atomic_numbers: np.ndarray) -> float:
    """Calculates the summed atomic mass for the given atomic numbers.

    Args:
        atomic_numbers: Array of valid atomic numbers

    Returns:
        The atomic mass in kilograms.
    """
    # It is assumed that the atomic numbers are valid at this point.
    mass = np.sum(atomic_masses[atomic_numbers])
    return mass


def get_volume(parallelepiped: np.ndarray) -> float:
    """Calculates a volume of the given parallelepiped.

    Args:
        cell: The parallellepiped as 3x3 matrix with cell basis vectors as
        rows.

    Returns:
        The cell volume.
    """
    return np.abs(np.linalg.det(parallelepiped))


def find_match(pos: np.array, positions: np.array, eps: float) -> Union[int, None]:
    """Attempts to find a position within a larger list of positions.

    Args:
        pos: The point to search for
        positions: The points within which the search is performed.
        eps: Match tolerance.

    Returns:
        Index of the matched position or None if match not found.
    """
    displacements = positions - pos
    distances = np.linalg.norm(displacements, axis=1)
    min_arg = np.argmin(distances)
    min_value = distances[min_arg]
    if min_value <= eps:
        return min_arg
    else:
        return None


def get_symmetry_string(space_group: int, wyckoff_sets: List[WyckoffSet]) -> str:
    """Used to serialize symmetry information into a string. The Wyckoff
    positions are assumed to be normalized and ordered as is the case if using
    the matid-library.

    Args:
        space_group: 3D space group number
        wyckoff_sets: Wyckoff sets that map a Wyckoff letter to related
            information

    Returns:
        A string that encodes the symmetry properties of an atomistic
        structure.
    """
    wyckoff_strings = []
    for group in wyckoff_sets:
        element = group.element
        wyckoff_letter = group.wyckoff_letter
        n_atoms = len(group.indices)
        i_string = "{} {} {}".format(element, wyckoff_letter, n_atoms)
        wyckoff_strings.append(i_string)
    wyckoff_string = ", ".join(sorted(wyckoff_strings))
    string = "{} {}".format(space_group, wyckoff_string)

    return string


def get_lattice_parameters(normalized_cell: np.ndarray) -> np.ndarray:
    """Calculate the lattice parameters for the normalized cell.

    Args:
        normalized_cell: The normalized cell as a 3x3 array. Each row is a
            basis vector.

    Returns:
        Six parameters a, b, c, alpha, beta, gamma (in this order) as a numpy
        array. Here is an explanation of each parameter:

        a = length of first basis vector
        b = length of second basis vector
        c = length of third basis vector
        alpha = angle between b and c
        beta  = angle between a and c
        gamma = angle between a and b
    """
    if normalized_cell is None:
        return None

    # Lengths
    lengths = np.linalg.norm(normalized_cell, axis=1)
    a, b, c = lengths

    # Angles
    angles = np.zeros(3)
    for i in range(3):
        j = (i + 1) % 3
        k = (i + 2) % 3
        angles[i] = np.dot(
            normalized_cell[j],
            normalized_cell[k]) / (lengths[j] * lengths[k])
    angles = np.clip(angles, -1.0, 1.0)
    alpha, beta, gamma = np.arccos(angles)

    return [a, b, c, alpha, beta, gamma]


def get_hill_decomposition(atom_labels: np.ndarray, reduced: bool = False) -> Tuple[List[str], List[int]]:
    """Given a list of atomic labels, returns the chemical formula using the
    Hill system (https://en.wikipedia.org/wiki/Hill_system) with an exception
    for binary ionic compounds where the cation is always given first.

    Args:
        atom_labels: Atom labels.
        reduced: Whether to divide the number of atoms by the greatest common
            divisor

    Returns:
        An ordered list of chemical symbols and the corresponding counts.
    """
    # Count occurancy of elements
    names = []
    counts = []
    unordered_names, unordered_counts = np.unique(atom_labels, return_counts=True)
    element_count_map = dict(zip(unordered_names, unordered_counts))

    # Apply basic Hill system:
    # 1. Is Carbon part of the system?
    if "C" in element_count_map:
        names.append("C")
        counts.append(element_count_map["C"])
        del element_count_map['C']

        # 1a. add hydrogren
        if "H" in element_count_map:
            names.append("H")
            counts.append(element_count_map["H"])
            del element_count_map["H"]

    # 2. all remaining elements in alphabetic order
    for element in sorted(element_count_map):
        names.append(element)
        counts.append(element_count_map[element])

    # 3. Binary ionic compounds: cation first, anion second
    # If any of the most electronegative elements is first
    # by alphabetic order, we move it to second
    if len(counts) == 2 and names != ["C", "H"]:
        order = {
            "F": 1,
            "O": 2,
            "N": 3,
            "Cl": 4,
            "Br": 5,
            "C": 6,
            "Se": 7,
            "S": 8,
            "I": 9,
            "As": 10,
            "H": 11,
            "P": 12,
            "Ge": 13,
            "Te": 14,
            "B": 15,
            "Sb": 16,
            "Po": 17,
            "Si": 18,
            "Bi": 19
        }
        if (names[0] in order):
            if (names[1] in order):
                if(order[names[0]] < order[names[1]]):
                    # For non-metals:
                    # Swap symbols and counts if first element
                    # is more electronegative than the second one,
                    # because the more electronegative element is the anion
                    names[0], names[1] = names[1], names[0]
                    counts[0], counts[1] = counts[1], counts[0]
            else:
                # Swap symbols and counts always if second element
                # is any other element,i.e.,
                # put non-metal last because it is the anion
                names[0], names[1] = names[1], names[0]
                counts[0], counts[1] = counts[1], counts[0]

    # TODO: implement all further exceptions regarding ordering
    #       in chemical formulas:
    #         - ionic compounds (ordering wrt to ionization)
    #         - oxides, acids, hydroxides...

    # Reduce if requested
    if reduced:
        greatest_common_divisor = reduce(gcd, counts)
        counts = np.array(counts) / greatest_common_divisor

    return names, counts


def get_formula_string(symbols: List[str], counts: List[int]) -> str:
    """Used to form a single formula string from a list of chemical species and
    their counts.

    Args:
        symbols: List of chemical species
        counts: List of chemical species occurences

    Returns:
        The formula as a string.
    """
    formula = ""
    for symbol, count in zip(symbols, counts):
        if count > 1:
            formula += "%s%d" % (symbol, count)
        else:
            formula += symbol
    return formula


def get_normalized_wyckoff(atomic_numbers: np.array, wyckoff_letters: np.array) -> Dict[str, Dict[str, int]]:
    """Returns a normalized Wyckoff sequence for the given atomic numbers and
    corresponding wyckoff letters. In a normalized sequence the chemical
    species are "anonymized" by replacing them with upper case alphabets.

    Args:
        atomic_numbers: Array of atomic numbers.
        wyckoff_letters: Array of Wyckoff letters as strings.

    Returns:
        Returns a dictionary that maps each present Wyckoff letter to a
        dictionary. The dictionary contains the number of atoms for each
        species, where the species names have been anomymized in the form
        "X_<index>".
    """
    # Count the occurrence of each chemical species
    atom_count: Dict[int, int] = {}
    for atomic_number in atomic_numbers:
        atom_count[atomic_number] = atom_count.get(atomic_number, 0) + 1

    # Form a dictionary that maps Wyckoff letters to a dictionary with the
    # number of atoms of that Wyckoff letter for each atomic number
    wyc_dict: dict = {}
    for i, wyckoff_letter in enumerate(wyckoff_letters):
        old_val = wyc_dict.get(wyckoff_letter, {})
        atomic_number = atomic_numbers[i]
        old_val[atomic_number] = old_val.get(atomic_number, 0) + 1
        wyc_dict[wyckoff_letter] = old_val
    sorted_wyckoff_letters = list(wyc_dict.keys())
    sorted_wyckoff_letters.sort()

    # Anonymize the atomic species to X_<index>, where the index is calculated
    # by ordering the species.
    def compare_atomic_number(at1, at2):
        def cmpp(a, b):
            return ((a < b) - (a > b))

        c = cmpp(atom_count[at1], atom_count[at2])
        if (c != 0):
            return c
        for wyckoff_letter in sorted_wyckoff_letters:
            p = wyc_dict[wyckoff_letter]
            c = cmpp(p.get(at1, 0), p.get(at2, 0))
            if c != 0:
                return c
        return 0
    sorted_species = list(atom_count.keys())
    sorted_species.sort(key=functools.cmp_to_key(compare_atomic_number))
    standard_atom_names = {}
    for i, at in enumerate(sorted_species):
        standard_atom_names[at] = ("X_%d" % i)

    # Rename with anonymized species labels
    standard_wyc: dict = {}
    for wk, ats in wyc_dict.items():
        std_ats = {}
        for at, count in ats.items():
            std_ats[standard_atom_names[at]] = count
        standard_wyc[wk] = std_ats

    # Divide atom counts with greatest common divisor
    if standard_wyc:
        counts = [c for x in standard_wyc.values() for c in x.values()]
        gcd = counts[0]
        for c in counts[1:]:
            gcd = fractions.gcd(gcd, c)
        if gcd != 1:
            for d in standard_wyc.values():
                for at, c in d.items():
                    d[at] = c // gcd

    return standard_wyc


def search_aflow_prototype(space_group: int, norm_wyckoff: dict) -> dict:
    """Searches the AFLOW prototype library for a match for the given space
    group and normalized Wyckoff sequence. The normalized Wyckoff sequence is
    assumed to come from the MatID symmetry routine.

    Currently only contains Part I of the prototype library (M. J. Mehl, D.
    Hicks, C. Toher, O. Levy, R. M. Hanson, G. L. W. Hart, and S. Curtarolo,
    The AFLOW Library of Crystallographic Prototypes: Part 1, Comp. Mat. Sci.
    136, S1-S828 (2017), 10.1016/j.commatsci.2017.01.017)

    Args:
        space_group_number: Space group number
        norm_wyckoff: Normalized Wyckoff occupations

    Returns:
        Dictionary containing the AFLOW prototype information.
    """
    structure_type_info = None
    type_descriptions: Any = aflow_prototypes["prototypes_by_spacegroup"].get(space_group, [])
    for type_description in type_descriptions:
        current_norm_wyckoffs = type_description.get("normalized_wyckoff_matid")
        if current_norm_wyckoffs and current_norm_wyckoffs == norm_wyckoff:
            structure_type_info = type_description
            break
    return structure_type_info


def get_brillouin_zone(reciprocal_lattice: np.array) -> dict:
    """Calculates the Brillouin Zone information from the given reciprocal
    lattice.

    This function uses the crystallographic definition, so there is no factor
    of 2*Pi.

    Args:
        primitive_lattice: The primitive cell as a matrix where rows are the
            cell basis vectors.

    Returns:
        A dictionary containing:
        "vertices": The vertices of the first Brillouin zone
        "faces": The indices of the vertices that make up the faces on the
            first Brillouin zone. The order of these indices matter, because
            only when combined sequentially they form the correct face.
    """
    # Create the near lattice points that surround the origin
    b1 = reciprocal_lattice[0, :]
    b2 = reciprocal_lattice[1, :]
    b3 = reciprocal_lattice[2, :]

    list_k_points = []
    for i, j, k in itertools.product([-1, 0, 1], [-1, 0, 1], [-1, 0, 1]):
        list_k_points.append(i * b1 + j * b2 + k * b3)

    # Create the first Brillouin zone by calculating a Voronoi cell starting
    # from the reciprocal cell origin.
    voronoi = Voronoi(list_k_points)
    origin_index = 13

    # Get the vertices. The regions attribute will contain a list of
    # different regions that were found during the Voronoi creation. We want
    # the Voronoi region for the point at the origin.
    point_region = voronoi.point_region[13]
    vertice_indices = voronoi.regions[point_region]
    vertices = voronoi.vertices[vertice_indices].tolist()

    # Create a mapping between the original index and an index in the new list
    index_map = {
        old_id: new_id for (new_id, old_id) in enumerate(vertice_indices)
    }

    # The ridges are the faces of a 3D Voronoi cell. Here we search for ridges
    # that are placed between the origin and some other point. These form the
    # BZ faces.
    faces = []
    for key in voronoi.ridge_dict:
        if key[0] == origin_index or key[1] == origin_index:
            ridge_indices = voronoi.ridge_dict[key]
            new_ridge_indices = [index_map[i] for i in ridge_indices]
            faces.append(new_ridge_indices)
    faces = faces

    brillouin_zone = {
        "vertices": vertices,
        "faces": faces,
    }
    return brillouin_zone