/*
 * Copyright The NOMAD Authors.
 *
 * This file is part of NOMAD. See https://nomad-lab.eu for further info.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import React from 'react'
import 'regenerator-runtime/runtime'
import { render, screen, archives, wait } from '../../testSetup'
import { expectPlotButtons, expectQuantity } from '../../testHelpers'
import { waitFor, within } from '@testing-library/dom'
import { getIndex } from '../../../tests/DFTBulk'
import { useApi } from '../api'
import OverviewView from './OverviewView'
import {
  testComposition,
  testSymmetry,
  testLatticeParameters
} from './properties/MaterialCard.spec'

jest.mock('../api')
const index = getIndex()

beforeAll(() => {
  // API mock init
  useApi.mockReturnValue({
    api: {
      post: () => wait({response: {data: {archive: archives.get(index.entry_id)}}}), // results
      get: () => wait({response: { // entry metadata
        entry_id: index.entry_id,
        data: index
      }})
    }
  })
})

afterAll(() => {
  // API mock cleanup
  jest.unmock('../api')
})

test('correctly renders metadata and all properties', async () => {
  render(<OverviewView entryId={index.entry_id} uploadId="dont-care" />)

  // Wait to load the entry metadata, i.e. wait for an arbitrary placeholder to appear
  await waitFor(() => {
    expect(screen.getByTestId('dos-electronic-placeholder')).toBeInTheDocument()
  })

  // Check if all method quantities are shown (on the left)
  expectQuantity('results.method.simulation.program_name', index)
  expectQuantity('results.method.simulation.program_version', index)
  expectQuantity('results.method.simulation.dft.xc_functional_type', index)
  expectQuantity('results.method.simulation.dft.xc_functional_names', index.results.method.simulation.dft.xc_functional_names.join(', '))
  expectQuantity('results.method.simulation.dft.basis_set_type', index)
  expectQuantity('results.method.simulation.dft.basis_set_name', index)
  expectQuantity('results.method.simulation.dft.van_der_Waals_method', index)
  expectQuantity('results.method.simulation.dft.relativity_method', index)

  // Check if all metadata is shown (on the left)
  expectQuantity('results.method.method_name', index)
  expectQuantity('comment', index)
  expectQuantity('references', index.references[0])
  expectQuantity('authors', index.authors[0].name)
  expectQuantity('datasets', index.datasets[0].dataset_name)
  expectQuantity('mainfile', index)
  expectQuantity('entry_id', index)
  expectQuantity('upload_id', index)
  expectQuantity('results.material.material_id', index)
  expectQuantity('upload_create_time', new Date(index.upload_create_time).toLocaleString())
  expectQuantity('last_processing_time', new Date(index.last_processing_time).toLocaleString())
  expectQuantity(undefined, `${index.nomad_version}/${index.nomad_commit}`, 'processing version', 'Version used in the last processing')

  // Check if all material data is shown (on the right, in the materials card)
  testComposition(index)
  testSymmetry(index)
  testLatticeParameters(index)
  // testStructure(index) // TODO: The click introduced here breaks the subsequent tests

  // Check if all the property cards are shown
  expect(screen.getByText('Electronic properties')).toBeInTheDocument()
  expect(screen.getByText('Band structure')).toBeInTheDocument()
  expect(screen.getByText('Density of states')).toBeInTheDocument()
  expect(screen.getByText('Brillouin zone')).toBeInTheDocument()

  expect(screen.getByText('Vibrational properties')).toBeInTheDocument()
  expect(screen.getByText('Phonon dispersion')).toBeInTheDocument()
  expect(screen.getByText('Phonon density of states')).toBeInTheDocument()
  expect(screen.getByText('Heat capacity')).toBeInTheDocument()
  expect(screen.getByText('Helmholtz free energy')).toBeInTheDocument()
  expect(screen.getByText('Mechanical properties')).toBeInTheDocument()
  expect(screen.getByText('Energy-volume curve')).toBeInTheDocument()
  expect(screen.getByText('Bulk modulus')).toBeInTheDocument()
  expect(screen.getByText('Shear modulus')).toBeInTheDocument()

  // Check if all visualization placeholders are shown
  const dosPhononPlaceholder = screen.getByTestId('dos-phonon-placeholder')
  expect(dosPhononPlaceholder).toBeInTheDocument()
  const bsPhononPlaceholder = screen.getByTestId('bs-phonon-placeholder')
  expect(bsPhononPlaceholder).toBeInTheDocument()
  const heatCapacityPlaceholder = screen.getByTestId('heat-capacity-placeholder')
  expect(heatCapacityPlaceholder).toBeInTheDocument()
  const energyFreePlaceholder = screen.getByTestId('energy-free-placeholder')
  expect(energyFreePlaceholder).toBeInTheDocument()
  const dosElectronicPlaceholder = screen.getByTestId('dos-electronic-placeholder')
  expect(dosElectronicPlaceholder).toBeInTheDocument()
  const bsElectronicPlaceholder = screen.getByTestId('bs-electronic-placeholder')
  expect(bsElectronicPlaceholder).toBeInTheDocument()
  const energyVolumeCurvePlaceholder = screen.getByTestId('energy-volume-curve-placeholder')
  expect(energyVolumeCurvePlaceholder).toBeInTheDocument()

  // Check if all placeholders disappear
  await waitFor(() => { expect(dosElectronicPlaceholder).not.toBeInTheDocument() })
  await waitFor(() => { expect(bsElectronicPlaceholder).not.toBeInTheDocument() })
  await waitFor(() => { expect(dosPhononPlaceholder).not.toBeInTheDocument() })
  await waitFor(() => { expect(bsPhononPlaceholder).not.toBeInTheDocument() })
  await waitFor(() => { expect(heatCapacityPlaceholder).not.toBeInTheDocument() })
  await waitFor(() => { expect(energyFreePlaceholder).not.toBeInTheDocument() })
  await waitFor(() => { expect(energyVolumeCurvePlaceholder).not.toBeInTheDocument() })

  // The test DOM does not support canvas or WebGL, and trying to add mocks for
  // them does not seem to work ATM. Thus we expect a message saying that the
  // 3D viewers are disabled.
  const msgs = screen.getAllByText('Could not display the visualization as your browser does not support WebGL content.')
  expect(msgs).toHaveLength(2)

  // Check that plot buttons are displayed
  const dosElectronic = screen.getByTestId('dos-electronic')
  expectPlotButtons(dosElectronic)
  const bsElectronic = screen.getByTestId('bs-electronic')
  expectPlotButtons(bsElectronic)
  const bsPhonon = screen.getByTestId('bs-phonon')
  expectPlotButtons(bsPhonon)
  const dosPhonon = screen.getByTestId('dos-phonon')
  expectPlotButtons(dosPhonon)
  const heatCapacity = screen.getByTestId('heat-capacity')
  expectPlotButtons(heatCapacity)
  const energyFree = screen.getByTestId('energy-free')
  expectPlotButtons(energyFree)
  const energyVolumeCurve = screen.getByTestId('energy-volume-curve')
  expectPlotButtons(energyVolumeCurve)

  // Check that tables are shown
  const bulkModulus = screen.getByTestId('bulk-modulus')
  expect(within(bulkModulus).getByText('Type')).toBeInTheDocument()
  expect(within(bulkModulus).getByText('Value (GPa)')).toBeInTheDocument()
  expect(within(bulkModulus).getByText('murnaghan')).toBeInTheDocument()
  const shearModulus = screen.getByTestId('shear-modulus')
  expect(within(shearModulus).getByText('Type')).toBeInTheDocument()
  expect(within(shearModulus).getByText('Value (GPa)')).toBeInTheDocument()
  expect(within(shearModulus).getByText('voigt_reuss_hill_average')).toBeInTheDocument()
})